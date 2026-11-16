"""The eTIMS library against KRA's OSCU v2.0 specification: request
shape, headers, result codes. No database and no KRA needed."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from friday_common.etims import (
    EtimsConfig,
    EtimsError,
    OscuClient,
    SaleDocument,
    SaleLine,
    is_kra_pin,
    item_body,
    item_code,
    normalize_pin,
    sale_body,
)


def test_kra_pin_format():
    assert is_kra_pin("P051234567X")
    assert is_kra_pin(" a123456789z ")
    assert normalize_pin(" p051 234567x") == "P051234567X"
    assert not is_kra_pin("B051234567X")  # A or P only
    assert not is_kra_pin("P05123456X")  # nine digits
    assert not is_kra_pin("")


def two_line_sale(**kw) -> SaleDocument:
    # KRA's own sample: 2 x 3,500 and 1 x 3,500, both tax type B,
    # prices with VAT inside (here 16%).
    return SaleDocument(
        number="POS-20261116-AB12CD",
        trader_no=123,
        issued_at=datetime(2026, 11, 16, 9, 30, tzinfo=UTC),
        lines=[
            SaleLine(name="Sugar 1kg", quantity=Decimal(2), unit_price_cents=350000, total_cents=700000, vat_cents=96552, tax_code="B", item_code="KE2NTKG0000001", item_class="5059690800", quantity_unit="KG"),
            SaleLine(name="Bread", quantity=Decimal(1), unit_price_cents=350000, total_cents=350000, vat_cents=48276, tax_code="B"),
        ],
        rates={"B": 16, "E": 8},
        **kw,
    )


def test_sale_body_follows_the_specification():
    body = sale_body(two_line_sale(buyer_pin="P051234567X", buyer_name="Duka Ltd", payment_method="mpesa"))
    assert body["invcNo"] == 123 and body["orgInvcNo"] == 0
    assert body["trdInvcNo"] == "POS-20261116-AB12CD"
    assert body["rcptTyCd"] == "S" and body["salesTyCd"] == "N" and body["salesSttsCd"] == "02"
    assert body["pmtTyCd"] == "06"  # mobile money
    assert body["custTin"] == "P051234567X" and body["receipt"]["custTin"] == "P051234567X"
    # Kenyan time: 09:30 UTC is 12:30 in Nairobi.
    assert body["cfmDt"] == "20261116123000" and body["salesDt"] == "20261116"
    assert body["totItemCnt"] == 2
    assert body["taxblAmtB"] == 10500.0 and body["taxAmtB"] == 1448.28 and body["taxRtB"] == 16
    assert body["taxblAmtA"] == 0 and body["taxRtE"] == 8
    assert body["totTaxblAmt"] == 10500.0 and body["totAmt"] == 10500.0 and body["totTaxAmt"] == 1448.28
    first = body["itemList"][0]
    assert first["itemSeq"] == 1 and first["qty"] == 2.0 and first["prc"] == 3500.0
    assert first["splyAmt"] == 7000.0 and first["taxblAmt"] == 7000.0 and first["taxAmt"] == 965.52
    assert first["qtyUnitCd"] == "KG" and first["itemCd"] == "KE2NTKG0000001"
    assert body["itemList"][1]["qtyUnitCd"] == "U"
    json.dumps(body)  # serialisable as sent


def test_prices_without_vat_and_a_discount():
    doc = SaleDocument(
        number="INV-1",
        trader_no=7,
        issued_at=datetime(2026, 11, 16, tzinfo=UTC),
        prices_include_tax=False,
        lines=[SaleLine(name="Rice", quantity=Decimal(1), unit_price_cents=100000, total_cents=90000, vat_cents=14400, discount_bp=1000, tax_code="B")],
    )
    item = sale_body(doc)["itemList"][0]
    # 900 + 144 VAT = 1,044 after a 10% discount on 1,160.
    assert item["taxblAmt"] == 1044.0 and item["taxAmt"] == 144.0
    assert item["splyAmt"] == 1160.0 and item["dcAmt"] == 116.0 and item["dcRt"] == 10.0


def test_credit_note_refers_to_the_sale():
    body = sale_body(two_line_sale(credit_note_of=123))
    assert body["rcptTyCd"] == "R" and body["orgInvcNo"] == 123 and body["rfdRsnCd"] == "06"
    # Amounts are positive on a credit note even though Friday's return lines are negative.
    neg = two_line_sale(credit_note_of=123)
    for line in neg.lines:
        line.total_cents, line.vat_cents, line.quantity = -line.total_cents, -line.vat_cents, -line.quantity
    assert sale_body(neg)["totAmt"] == 10500.0


def test_item_code_and_body():
    assert item_code("2", "NT", "U", 12) == "KE2NTU0000012"
    body = item_body(code="KE2NTU0000012", name="Bread", item_class="5022110801", tax_code="B", price_cents=6500, is_service=False)
    assert body["itemTyCd"] == "2" and body["dftPrc"] == 65.0 and body["taxTyCd"] == "B" and body["useYn"] == "Y"


def kra(handler):
    return httpx.MockTransport(handler)


async def test_client_sends_the_headers_and_reads_the_result():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = request.headers
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"resultCd": "000", "resultMsg": "It is succeeded", "resultDt": "20261116123000", "data": {"curRcptNo": 1, "totRcptNo": 1, "intrlData": "EAHSAV6ECUUXSY6PCCJYAUP6MI", "rcptSign": "QUII27MATATSHFRB", "sdcDateTime": "20261116123001"}})

    cfg = EtimsConfig(tin="P051234567X", branch_id="00", environment="sandbox", cmc_key="k")
    out = await OscuClient(cfg, transport=kra(handler)).save_sale(sale_body(two_line_sale()))
    assert seen["url"] == "https://etims-api-sbx.kra.go.ke/etims-api/saveTrnsSalesOsdc"
    assert seen["headers"]["tin"] == "P051234567X" and seen["headers"]["bhfId"] == "00" and seen["headers"]["cmcKey"] == "k"
    assert seen["body"]["tin"] == "P051234567X" and seen["body"]["bhfId"] == "00"
    assert out["rcptSign"] == "QUII27MATATSHFRB"


async def test_client_errors_and_customer_lookup():
    def refuse(request):
        return httpx.Response(200, json={"resultCd": "910", "resultMsg": "Request parameter error"})

    cfg = EtimsConfig(tin="P051234567X", cmc_key="k")
    with pytest.raises(EtimsError) as err:
        await OscuClient(cfg, transport=kra(refuse)).save_sale({})
    assert err.value.code == "910"

    def none_found(request):
        return httpx.Response(200, json={"resultCd": "001", "resultMsg": "There is no search result", "data": None})

    assert await OscuClient(cfg, transport=kra(none_found)).lookup_customer("A123456789Z") is None

    def found(request):
        assert json.loads(request.content)["custmTin"] == "A123456789Z"
        return httpx.Response(200, json={"resultCd": "000", "data": {"custList": [{"tin": "A123456789Z", "taxprNm": "TAXPAYER1", "taxprSttsCd": "A"}]}})

    who = await OscuClient(cfg, transport=kra(found)).lookup_customer("A123456789Z")
    assert who["taxprNm"] == "TAXPAYER1"

    def down(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(EtimsError) as err:
        await OscuClient(cfg, transport=kra(down)).lookup_customer("A123456789Z")
    assert err.value.code == ""


def test_vscu_uses_the_local_address():
    cfg = EtimsConfig(tin="P051234567X", mode="vscu", vscu_url="http://192.168.1.20:8088/")
    assert cfg.base_url == "http://192.168.1.20:8088"
