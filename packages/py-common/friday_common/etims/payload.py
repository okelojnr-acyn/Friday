"""Builds the bodies of KRA's eTIMS OSCU calls from Friday's own data:
/saveTrnsSalesOsdc (a sale or credit note) and /saveItem (a product).
Pure functions, so the same code fills the manual filing sheet and the
automated sender, and tests check them without KRA.

Amounts follow the specification's sample: an item's taxable amount is
VAT-inclusive (taxblAmt = totAmt) and taxAmt is the VAT inside it. Money
is shillings with two decimals."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from .codes import (
    CREDIT_NOTE_REFUND,
    PAYMENT_METHODS,
    PAYMENT_OTHER,
    PRODUCT_FINISHED,
    PRODUCT_SERVICE,
    RECEIPT_CREDIT_NOTE,
    RECEIPT_SALE,
    SALES_STATUS_APPROVED,
    SALES_TYPE_NORMAL,
    TAX_TYPES,
)

# Kenya keeps UTC+3 all year (no daylight saving).
NAIROBI = timezone(timedelta(hours=3))
CODES = ("A", "B", "C", "D", "E")


def money(cents: int | Decimal) -> float:
    return float((Decimal(cents) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def kra_time(t: datetime) -> str:
    """yyyyMMddHHmmss in Kenyan time, as eTIMS expects."""
    return t.astimezone(NAIROBI).strftime("%Y%m%d%H%M%S")


@dataclass
class SaleLine:
    name: str
    quantity: Decimal
    unit_price_cents: int  # as rung up: VAT-inclusive when the document says so
    total_cents: int  # after discount, same VAT basis as unit_price_cents
    vat_cents: int  # VAT inside (inclusive) or on top of (exclusive) total_cents
    tax_code: str = "B"
    discount_bp: int = 0
    item_code: str = ""
    item_class: str = ""
    barcode: str = ""
    packaging_unit: str = "NT"
    quantity_unit: str = "U"


@dataclass
class SaleDocument:
    number: str  # Friday's own number, e.g. POS-20261116-AB12CD
    trader_no: int  # eTIMS invoice number: one sequence per branch
    issued_at: datetime
    lines: list[SaleLine]
    prices_include_tax: bool = True
    buyer_pin: str = ""
    buyer_name: str = ""
    payment_method: str = "cash"
    credit_note_of: int = 0  # trader_no of the sale a credit note refunds
    rates: dict[str, int] = field(default_factory=dict)  # code -> percent
    business_name: str = ""
    user: str = "friday"

    @property
    def is_credit_note(self) -> bool:
        return self.credit_note_of > 0


def line_amounts(line: SaleLine, inclusive: bool) -> dict:
    """One line's VAT-inclusive figures: before discount, the discount,
    after discount and the VAT inside."""
    qty = abs(Decimal(line.quantity)) or Decimal(1)
    total = abs(line.total_cents)
    vat = abs(line.vat_cents)
    gross = total if inclusive else total + vat
    # The undiscounted amount, on the same VAT-inclusive basis.
    if line.discount_bp and line.discount_bp < 10_000:
        before = (Decimal(gross) * 10_000 / (10_000 - line.discount_bp)).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    else:
        before = Decimal(gross)
    return {
        "qty": qty,
        "price": before / qty,
        "supply": before,
        "discount": before - gross,
        "gross": Decimal(gross),
        "vat": Decimal(vat),
    }


def sale_body(doc: SaleDocument) -> dict:
    """The /saveTrnsSalesOsdc request for one sale or credit note."""
    when = kra_time(doc.issued_at)
    items = []
    taxable = {c: Decimal(0) for c in CODES}
    tax = {c: Decimal(0) for c in CODES}
    for seq, line in enumerate(doc.lines, start=1):
        code = line.tax_code if line.tax_code in CODES else "B"
        a = line_amounts(line, doc.prices_include_tax)
        taxable[code] += a["gross"]
        tax[code] += a["vat"]
        items.append(
            {
                "itemSeq": seq,
                "itemCd": line.item_code or None,
                "itemClsCd": line.item_class or None,
                "itemNm": line.name[:200],
                "bcd": line.barcode or None,
                "pkgUnitCd": line.packaging_unit or "NT",
                "pkg": float(a["qty"]),
                "qtyUnitCd": line.quantity_unit or "U",
                "qty": float(a["qty"]),
                "prc": money(a["price"]),
                "splyAmt": money(a["supply"]),
                "dcRt": round(line.discount_bp / 100, 2),
                "dcAmt": money(a["discount"]),
                "isrccCd": None,
                "isrccNm": None,
                "isrcRt": None,
                "isrcAmt": None,
                "taxTyCd": code,
                "taxblAmt": money(a["gross"]),
                "taxAmt": money(a["vat"]),
                "totAmt": money(a["gross"]),
            }
        )
    rates = {c: doc.rates.get(c, TAX_TYPES[c][1]) for c in CODES}
    body = {
        "trdInvcNo": doc.number[:50],
        "invcNo": doc.trader_no,
        "orgInvcNo": doc.credit_note_of,
        "custTin": doc.buyer_pin or None,
        "custNm": doc.buyer_name[:60] or None,
        "salesTyCd": SALES_TYPE_NORMAL,
        "rcptTyCd": RECEIPT_CREDIT_NOTE if doc.is_credit_note else RECEIPT_SALE,
        "pmtTyCd": PAYMENT_METHODS.get(doc.payment_method, PAYMENT_OTHER),
        "salesSttsCd": SALES_STATUS_APPROVED,
        "cfmDt": when,
        "salesDt": when[:8],
        "stockRlsDt": when,
        "cnclReqDt": None,
        "cnclDt": None,
        "rfdDt": when if doc.is_credit_note else None,
        "rfdRsnCd": CREDIT_NOTE_REFUND if doc.is_credit_note else None,
        "totItemCnt": len(items),
        "totTaxblAmt": money(sum(taxable.values())),
        "totTaxAmt": money(sum(tax.values())),
        "totAmt": money(sum(taxable.values())),
        "prchrAcptcYn": "N",
        "remark": None,
        "regrId": doc.user[:20],
        "regrNm": doc.user[:60],
        "modrId": doc.user[:20],
        "modrNm": doc.user[:60],
        "receipt": {
            "custTin": doc.buyer_pin or None,
            "custMblNo": None,
            "rcptPbctDt": when,
            "trdeNm": doc.business_name[:20] or None,
            "adrs": None,
            "topMsg": None,
            "btmMsg": None,
            "prchrAcptcYn": "N",
        },
        "itemList": items,
    }
    for c in CODES:
        body[f"taxblAmt{c}"] = money(taxable[c])
        body[f"taxRt{c}"] = rates[c]
        body[f"taxAmt{c}"] = money(tax[c])
    return body


def item_code(product_type: str, packaging_unit: str, quantity_unit: str, seq: int, country: str = "KE") -> str:
    """eTIMS item code (spec 4.19): country, product type, packaging unit,
    quantity unit and a 7-digit sequence, e.g. KE2NTU0000012."""
    return f"{country}{product_type}{packaging_unit}{quantity_unit}{seq:07d}"


def item_body(
    *,
    code: str,
    name: str,
    item_class: str,
    tax_code: str,
    price_cents: int,
    is_service: bool,
    packaging_unit: str = "NT",
    quantity_unit: str = "U",
    barcode: str = "",
    user: str = "friday",
) -> dict:
    """The /saveItem request for one product."""
    price = money(price_cents)
    return {
        "itemCd": code,
        "itemClsCd": item_class,
        "itemTyCd": PRODUCT_SERVICE if is_service else PRODUCT_FINISHED,
        "itemNm": name[:200],
        "itemStdNm": None,
        "orgnNatCd": "KE",
        "pkgUnitCd": packaging_unit,
        "qtyUnitCd": quantity_unit,
        "taxTyCd": tax_code,
        "btchNo": None,
        "bcd": barcode or None,
        "dftPrc": price,
        "grpPrcL1": price,
        "grpPrcL2": price,
        "grpPrcL3": price,
        "grpPrcL4": price,
        "grpPrcL5": None,
        "addInfo": None,
        "sftyQty": None,
        "isrcAplcbYn": "N",
        "useYn": "Y",
        "regrId": user[:20],
        "regrNm": user[:60],
        "modrId": user[:20],
        "modrNm": user[:60],
    }
