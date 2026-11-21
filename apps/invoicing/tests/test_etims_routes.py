"""eTIMS filing: the buyer's PIN from the till, the filing list, recording
KRA's number by hand, credit notes, the VAT3 sales CSV, and the automated
sender (against a fake KRA)."""

import csv
import io
import json
import uuid
from dataclasses import replace

import httpx
import pytest

from app import etims_routes

CFG = {
    "enabled": True,
    "environment": "sandbox",
    "mode": "oscu",
    "branch_id": "00",
    "device_serial": "KRA-001",
    "cmc_key": "k",
    "tax_pin": "P051234567X",
    "business_name": "Duka",
    "default_code": "B",
    "rates": [{"code": "A", "name": "Exempt", "rate_bp": 0}, {"code": "B", "name": "VAT", "rate_bp": 1600}],
}


@pytest.fixture(autouse=True)
def kernel_settings(monkeypatch):
    async def fake(org_id):
        return CFG

    monkeypatch.setattr(etims_routes, "get_etims_config", fake)


@pytest.fixture
def admin(as_principal, principal):
    as_principal(replace(principal, role="admin"))


def sale(buyer_pin="", **kw):
    body = {
        "client_sale_id": str(uuid.uuid4()),
        "currency": "KES",
        "method": "mpesa",
        "amount_cents": 116000 + 5000,
        "prices_include_tax": True,
        "lines": [
            {"description": "Cooking oil 1L", "quantity": 2, "unit_price_cents": 58000, "product_id": str(uuid.uuid4()), "tax_code": "B", "vat_cents": 16000, "etims_quantity_unit": "LTR"},
            {"description": "Maize flour 2kg", "quantity": 1, "unit_price_cents": 5000, "tax_code": "A", "vat_cents": 0},
        ],
        **kw,
    }
    if buyer_pin:
        body["buyer_pin"] = buyer_pin
        body["buyer_name"] = "Mama Mboga Ltd"
    return body


async def test_a_business_sale_waits_to_be_filed_and_records_krAs_number(client, admin):
    await client.post("/pos/sales", json=sale())  # walk-in: no PIN
    made = (await client.post("/pos/sales", json=sale(" p051234567x "))).json()

    rows = (await client.get("/etims/invoices")).json()  # default: buyer PIN, unfiled
    assert [r["number"] for r in rows] == [made["number"]]
    row = rows[0]
    assert row["buyer_pin"] == "P051234567X" and row["pin_ok"]
    assert row["by_code"]["B"] == {"gross_cents": 116000, "vat_cents": 16000}
    assert row["by_code"]["A"] == {"gross_cents": 5000, "vat_cents": 0}
    assert row["total_cents"] == 121000 and row["vat_cents"] == 16000
    assert len((await client.get("/etims/invoices", params={"scope": "all"})).json()) == 2

    detail = (await client.get(f"/etims/invoices/{row['id']}")).json()
    assert detail["lines"][0]["quantity_unit"] == "LTR" and detail["lines"][0]["tax_code"] == "B"
    assert detail["oscu_body"]["custTin"] == "P051234567X" and detail["oscu_body"]["taxAmtB"] == 160.0

    filed = await client.post(f"/etims/invoices/{row['id']}/filed", json={"etims_invoice_no": "KRAMW0012345"})
    assert filed.status_code == 200 and filed.json()["status"] == "submitted" and filed.json()["via"] == "manual"
    assert (await client.get("/etims/invoices")).json() == []
    # The buyer can't change once filed.
    r = await client.put(f"/etims/invoices/{row['id']}/buyer", json={"pin": "A123456789Z"})
    assert r.status_code == 409
    # A mistake can be undone.
    undone = (await client.post(f"/etims/invoices/{row['id']}/unfile")).json()
    assert undone["status"] == "unfiled" and undone["etims_invoice_no"] == ""


async def test_a_pin_added_after_the_sale(client, admin):
    made = (await client.post("/pos/sales", json=sale())).json()
    bad = await client.put(f"/etims/invoices/{made['id']}/buyer", json={"pin": "12345"})
    assert bad.status_code == 422
    ok = (await client.put(f"/etims/invoices/{made['id']}/buyer", json={"pin": "a123456789z", "name": "Kiosk"})).json()
    assert ok["buyer_pin"] == "A123456789Z"
    assert [r["id"] for r in (await client.get("/etims/invoices")).json()] == [made["id"]]


async def test_a_return_is_a_credit_note_naming_the_sale(client, a_till, admin):
    # a_till signs back in as a member; admin comes after it.
    shift = (await client.post("/pos/shifts/open", json={"opening_float_cents": 0})).json()
    made = (await client.post("/pos/sales", json=sale("P051234567X", shift_id=shift["id"]))).json()
    await client.post(f"/etims/invoices/{made['id']}/filed", json={"etims_invoice_no": "KRA-1"})
    ret = await client.post(f"/pos/sales/{made['number']}/return?shift_id={shift['id']}")
    assert ret.status_code == 201, ret.text
    rows = (await client.get("/etims/invoices")).json()
    assert len(rows) == 1 and rows[0]["credit_note"] and rows[0]["original_number"] == made["number"]
    assert rows[0]["original_etims_no"] == "KRA-1" and rows[0]["buyer_pin"] == "P051234567X"
    assert rows[0]["by_code"]["B"]["vat_cents"] == 16000  # amounts positive on a credit note

    month = made["created_at"][:7]
    rows = list(csv.reader(io.StringIO((await client.get("/etims/vat-sales.csv", params={"month": month})).text)))
    assert rows[0][0] == "PIN of Purchaser"
    by = {(r[4], r[6]): r for r in rows[1:]}
    # The sale under KRA's number; the return refers to it.
    assert by[("KRA-1", "B")][7:9] == ["1000.00", "160.00"] and by[("KRA-1", "B")][0] == "P051234567X"
    credit = [r for r in rows[1:] if r[9] == "KRA-1" and r[6] == "B"]
    assert credit and credit[0][7:9] == ["-1000.00", "-160.00"]


async def test_only_admins_see_the_filing_list(client, as_principal, principal):
    from dataclasses import replace

    as_principal(replace(principal, role="member"))
    assert (await client.get("/etims/invoices")).status_code == 403


async def test_pin_check_without_automation(client, monkeypatch):
    monkeypatch.delenv("ETIMS_AUTOMATION", raising=False)
    r = (await client.get("/etims/pin/p051234567x")).json()
    assert r["format_ok"] and r["verified"] is None and r["checker_url"].startswith("https://itax.kra.go.ke")
    assert not (await client.get("/etims/pin/123")).json()["format_ok"]


async def test_sending_is_refused_until_automation_is_on(client, admin, monkeypatch):
    monkeypatch.delenv("ETIMS_AUTOMATION", raising=False)
    assert (await client.post("/etims/send")).status_code == 409


async def test_automated_sending_against_a_fake_kra(client, admin, monkeypatch):
    monkeypatch.setenv("ETIMS_AUTOMATION", "1")
    posted = []

    def kra(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/selectCustomer"):
            return httpx.Response(200, json={"resultCd": "000", "data": {"custList": [{"tin": body["custmTin"], "taxprNm": "MAMA MBOGA LTD", "taxprSttsCd": "A"}]}})
        posted.append(body)
        if body["trdInvcNo"].startswith("POS") and body["custTin"] is None:
            return httpx.Response(200, json={"resultCd": "910", "resultMsg": "Request parameter error"})
        return httpx.Response(200, json={"resultCd": "000", "data": {"curRcptNo": 7, "totRcptNo": 9, "intrlData": "INTRL", "rcptSign": "SIGN", "sdcDateTime": "20261116120000"}})

    real = etims_routes.OscuClient
    monkeypatch.setattr(etims_routes, "OscuClient", lambda cfg: real(cfg, transport=httpx.MockTransport(kra)))

    who = (await client.get("/etims/pin/P051234567X")).json()
    assert who["verified"] and who["name"] == "MAMA MBOGA LTD" and who["active"]

    ok = (await client.post("/pos/sales", json=sale("P051234567X"))).json()
    refused = (await client.post("/pos/sales", json=sale())).json()
    result = (await client.post("/etims/send")).json()
    assert result == {"sent": 1, "failed": 1}
    assert {p["invcNo"] for p in posted} == {1, 2}  # one sequence per org

    rows = {r["number"]: r for r in (await client.get("/etims/invoices", params={"scope": "all", "status": "any"})).json()}
    assert rows[ok["number"]]["status"] == "submitted" and rows[ok["number"]]["etims_invoice_no"] == "7/9"
    assert rows[ok["number"]]["receipt_check_url"].endswith("P051234567X00SIGN")
    assert rows[refused["number"]]["status"] == "failed" and "910" in rows[refused["number"]]["error"]
    # A manual number can't overwrite what KRA sent.
    r = await client.post(f"/etims/invoices/{ok['id']}/filed", json={"etims_invoice_no": "x"})
    assert r.status_code == 409


async def test_a_reprinted_receipt_has_its_items_vat_and_once_signed_the_kra_block(client, admin, monkeypatch):
    made = (await client.post("/pos/sales", json=sale("P051234567X"))).json()
    r = (await client.get(f"/etims/receipt/{made['number']}")).json()
    assert r["number"] == made["number"] and r["buyer_pin"] == "P051234567X" and r["prices_include_vat"]
    assert [(line["description"], line["unit"], line["tax_code"]) for line in r["lines"]] == [("Cooking oil 1L", "LTR", "B"), ("Maize flour 2kg", "", "A")]
    assert r["vat"] == [
        {"code": "A", "rate_pct": 0, "taxable_cents": 5000, "vat_cents": 0},
        {"code": "B", "rate_pct": 16, "taxable_cents": 100000, "vat_cents": 16000},
    ]
    assert r["total_cents"] == 121000 and r["vat_cents"] == 16000
    assert r["payments"] == [{"method": "mpesa", "cents": 121000}]
    assert r["etims"] is None  # not filed with KRA yet

    # Signed by eTIMS (the automated sender, against a fake KRA).
    monkeypatch.setenv("ETIMS_AUTOMATION", "1")

    def kra(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/selectCustomer"):
            return httpx.Response(200, json={"resultCd": "000", "data": {"custList": [{"tin": "P051234567X", "taxprNm": "MAMA MBOGA LTD", "taxprSttsCd": "A"}]}})
        return httpx.Response(200, json={"resultCd": "000", "data": {"curRcptNo": 7, "totRcptNo": 9, "intrlData": "INTRL", "rcptSign": "SIGN", "sdcDateTime": "20261116120000"}})

    real = etims_routes.OscuClient
    monkeypatch.setattr(etims_routes, "OscuClient", lambda cfg: real(cfg, transport=httpx.MockTransport(kra)))
    assert (await client.post("/etims/send")).json()["sent"] == 1
    e = (await client.get(f"/etims/receipt/{made['number']}")).json()["etims"]
    assert (e["invoice_no"], e["internal_data"], e["receipt_sign"], e["sdc_time"]) == ("7/9", "INTRL", "SIGN", "20261116120000")
    assert e["check_url"].endswith("P051234567X00SIGN")
    assert e["qr_svg"].startswith("<svg") and "qrline" in e["qr_svg"]


async def test_a_receipt_filed_by_hand_carries_krAs_number_without_a_qr(client, admin):
    made = (await client.post("/pos/sales", json=sale("P051234567X"))).json()
    await client.post(f"/etims/invoices/{made['id']}/filed", json={"etims_invoice_no": "KRAMW0012345"})
    e = (await client.get(f"/etims/receipt/{made['number']}")).json()["etims"]
    assert e["invoice_no"] == "KRAMW0012345" and e["check_url"] == "" and e["qr_svg"] == ""
