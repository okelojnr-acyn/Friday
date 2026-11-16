"""KRA eTIMS for sales and credit notes.

Today (manual): Friday lists the sales that need an eTIMS invoice, shows
each one laid out the way the eTIMS portal asks for it (buyer PIN, items,
tax type A-E, VAT), and records the invoice number KRA gives back. A
business buyer's PIN is taken at the till or added afterwards.

Later (automated, ETIMS_AUTOMATION=1 after the production checks): the
same documents go to KRA's OSCU API (/saveTrnsSalesOsdc) and the receipt
numbers and signature come back into the same columns. PIN lookups use
OSCU's /selectCustomer.
"""

import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from friday_common import Principal, get_current_principal, get_org_session
from friday_common.auth import require_role
from friday_common.etims import (
    EtimsConfig,
    EtimsError,
    OscuClient,
    SaleDocument,
    SaleLine,
    is_kra_pin,
    normalize_pin,
    sale_body,
)
from friday_common.etims.codes import PIN_CHECKER_URL, RECEIPT_CHECK
from friday_common.etims.kernel import automation_on, get_etims_config
from friday_common.etims.payload import line_amounts
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Invoice

router = APIRouter(prefix="/etims", tags=["etims"])

STATUSES = ("unfiled", "submitted", "failed")


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


def is_credit_note(inv: Invoice) -> bool:
    return inv.number.startswith("RET-") or inv.source == "credit_note"


def _in_scope():
    """Documents KRA expects an eTIMS invoice for: issued invoices and
    till sales (a till sale later returned is still a sale), not drafts,
    quotes or unpaid gateway checkouts."""
    return and_(
        Invoice.kind == "invoice",
        or_(Invoice.status.in_(("sent", "paid")), and_(Invoice.status == "void", Invoice.source == "pos")),
    )


def _inclusive(inv: Invoice) -> bool:
    if inv.source == "pos" or inv.number.startswith("RET-"):
        return True if inv.prices_include_tax is None else inv.prices_include_tax
    return False  # typed invoices add each line's tax on top


def document_for(inv: Invoice, cfg: dict, credit_note_of: int = 0) -> SaleDocument:
    default_code = cfg.get("default_code") or "B"
    rates = {r["code"]: r["rate_bp"] / 100 for r in cfg.get("rates") or []}
    lines = []
    for line in inv.lines:
        if line.is_adjustment:
            continue
        vat = line.vat_cents or (line.tax_cents if line.tax_rate_bp else 0)
        lines.append(
            SaleLine(
                name=line.description,
                # A unit KRA has no code for goes out in the base unit.
                quantity=Decimal(line.quantity) * Decimal(line.etims_qty_factor or 1),
                unit_price_cents=line.unit_price_cents,
                total_cents=line.total_cents,
                vat_cents=vat,
                tax_code=line.tax_code or default_code,
                discount_bp=line.discount_bp,
                item_code=line.item_code,
                item_class=line.item_class,
                quantity_unit=line.quantity_unit or "U",
                packaging_unit=line.packaging_unit or "NT",
            )
        )
    pays = sorted(inv.payments, key=lambda p: abs(p.amount_cents), reverse=True)
    method = pays[0].method if pays else "credit"
    return SaleDocument(
        number=inv.number,
        trader_no=inv.etims_trader_no or 0,
        issued_at=inv.issued_at or inv.created_at,
        lines=lines,
        prices_include_tax=_inclusive(inv),
        buyer_pin=inv.buyer_pin,
        buyer_name=inv.buyer_name,
        payment_method=method,
        credit_note_of=credit_note_of,
        rates=rates,
        business_name=cfg.get("business_name", ""),
        user=(inv.cashier_email or "friday")[:20],
    )


def tax_by_code(doc: SaleDocument) -> dict[str, dict[str, int]]:
    """Per tax type: the VAT-inclusive amount and the VAT, in cents."""
    out: dict[str, dict[str, int]] = {}
    for line in doc.lines:
        a = line_amounts(line, doc.prices_include_tax)
        row = out.setdefault(line.tax_code, {"gross_cents": 0, "vat_cents": 0})
        row["gross_cents"] += int(a["gross"])
        row["vat_cents"] += int(a["vat"])
    return out


class EtimsRow(BaseModel):
    id: uuid.UUID
    number: str
    credit_note: bool
    original_number: str | None
    original_etims_no: str = ""
    issued_at: datetime | None
    buyer_pin: str
    buyer_name: str
    pin_ok: bool
    total_cents: int
    vat_cents: int
    by_code: dict[str, dict[str, int]]
    status: str
    via: str
    etims_invoice_no: str
    filed_at: datetime | None
    filed_by: str
    error: str
    receipt_check_url: str = ""


async def _originals(session: AsyncSession, org: uuid.UUID, invs: list[Invoice]) -> dict[str, Invoice]:
    numbers = {i.source_ref for i in invs if is_credit_note(i) and i.source_ref}
    if not numbers:
        return {}
    rows = await session.execute(select(Invoice).where(Invoice.org_id == org, Invoice.number.in_(numbers)))
    return {i.number: i for i in rows.scalars()}


def _row(inv: Invoice, cfg: dict, originals: dict[str, Invoice]) -> EtimsRow:
    orig = originals.get(inv.source_ref or "") if is_credit_note(inv) else None
    doc = document_for(inv, cfg, credit_note_of=(orig.etims_trader_no or 0) if orig else 0)
    codes = tax_by_code(doc)
    check = ""
    if inv.etims_receipt_sign and cfg.get("tax_pin"):
        base = RECEIPT_CHECK.get(cfg.get("environment") or "sandbox", "")
        check = f"{base}{cfg['tax_pin']}{cfg.get('branch_id') or '00'}{inv.etims_receipt_sign}"
    return EtimsRow(
        id=inv.id,
        number=inv.number,
        credit_note=is_credit_note(inv),
        original_number=inv.source_ref if is_credit_note(inv) else None,
        original_etims_no=orig.etims_invoice_no if orig else "",
        issued_at=inv.issued_at or inv.created_at,
        buyer_pin=inv.buyer_pin,
        buyer_name=inv.buyer_name,
        pin_ok=not inv.buyer_pin or is_kra_pin(inv.buyer_pin),
        total_cents=sum(c["gross_cents"] for c in codes.values()),
        vat_cents=sum(c["vat_cents"] for c in codes.values()),
        by_code=codes,
        status=inv.etims_status,
        via=inv.etims_via,
        etims_invoice_no=inv.etims_invoice_no,
        filed_at=inv.etims_filed_at,
        filed_by=inv.etims_filed_by,
        error=inv.etims_error,
        receipt_check_url=check,
    )


def _month_bounds(month: str | None) -> tuple[datetime, datetime] | None:
    if not month:
        return None
    try:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    except ValueError:
        raise HTTPException(422, "month is YYYY-MM") from None
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


@router.get("/invoices", response_model=list[EtimsRow])
async def list_etims_invoices(
    scope: str = Query("pin", pattern="^(pin|all)$"),
    status: str = Query("unfiled", pattern="^(unfiled|submitted|failed|any)$"),
    month: str | None = None,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """The filing list. scope=pin: sales to a business (buyer PIN given),
    the ones a buyer needs to claim; scope=all: every sale."""
    org = _org(principal)
    q = select(Invoice).where(Invoice.org_id == org, _in_scope())
    if scope == "pin":
        q = q.where(Invoice.buyer_pin != "")
    if status != "any":
        q = q.where(Invoice.etims_status == status)
    bounds = _month_bounds(month)
    if bounds:
        when = func.coalesce(Invoice.issued_at, Invoice.created_at)
        q = q.where(when >= bounds[0], when < bounds[1])
    invs = (await session.execute(q.order_by(func.coalesce(Invoice.issued_at, Invoice.created_at)).limit(500))).scalars().all()
    cfg = await get_etims_config(principal.org_id)
    originals = await _originals(session, org, invs)
    return [_row(i, cfg, originals) for i in invs]


async def _owned(session: AsyncSession, principal: Principal, invoice_id: uuid.UUID) -> Invoice:
    inv = await session.get(Invoice, invoice_id)
    if inv is None or inv.org_id != _org(principal):
        raise HTTPException(404, "invoice not found")
    await session.refresh(inv, attribute_names=["lines", "payments"])
    return inv


@router.get("/invoices/{invoice_id}")
async def etims_invoice_detail(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """One document laid out as the eTIMS portal asks for it, plus the
    exact body the automated sender would post."""
    inv = await _owned(session, principal, invoice_id)
    cfg = await get_etims_config(principal.org_id)
    originals = await _originals(session, _org(principal), [inv])
    row = _row(inv, cfg, originals)
    doc = document_for(inv, cfg, credit_note_of=0)
    lines = []
    for line in doc.lines:
        a = line_amounts(line, doc.prices_include_tax)
        lines.append(
            {
                "name": line.name,
                "quantity": float(a["qty"]),
                "quantity_unit": line.quantity_unit,
                "unit_price_cents": int(a["price"]),
                "discount_cents": int(a["discount"]),
                "tax_code": line.tax_code,
                "gross_cents": int(a["gross"]),
                "vat_cents": int(a["vat"]),
                "item_code": line.item_code,
            }
        )
    return {"invoice": row, "lines": lines, "oscu_body": sale_body(doc)}


class FiledIn(BaseModel):
    etims_invoice_no: str = Field(min_length=1, max_length=60)


@router.post("/invoices/{invoice_id}/filed", response_model=EtimsRow)
async def record_filed(
    invoice_id: uuid.UUID,
    body: FiledIn,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """Filed by hand in the eTIMS portal: keep the invoice number KRA gave."""
    inv = await _owned(session, principal, invoice_id)
    if inv.etims_status == "submitted" and inv.etims_via not in ("", "manual"):
        raise HTTPException(409, "this one was sent to KRA by Friday; its number came from KRA")
    inv.etims_status = "submitted"
    inv.etims_via = "manual"
    inv.etims_invoice_no = body.etims_invoice_no.strip()
    inv.etims_filed_at = datetime.now(UTC)
    inv.etims_filed_by = principal.email
    inv.etims_error = ""
    await session.commit()
    cfg = await get_etims_config(principal.org_id)
    return _row(inv, cfg, await _originals(session, _org(principal), [inv]))


@router.post("/invoices/{invoice_id}/unfile", response_model=EtimsRow)
async def undo_filed(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """Undo a number recorded by mistake (manual filings only)."""
    inv = await _owned(session, principal, invoice_id)
    if inv.etims_via not in ("", "manual"):
        raise HTTPException(409, "sent to KRA by Friday; correct it with a credit note instead")
    inv.etims_status = "unfiled"
    inv.etims_via = ""
    inv.etims_invoice_no = ""
    inv.etims_filed_at = None
    inv.etims_filed_by = ""
    await session.commit()
    cfg = await get_etims_config(principal.org_id)
    return _row(inv, cfg, await _originals(session, _org(principal), [inv]))


class BuyerIn(BaseModel):
    pin: str = Field(max_length=20)
    name: str = Field(default="", max_length=120)


@router.put("/invoices/{invoice_id}/buyer", response_model=EtimsRow)
async def set_buyer(
    invoice_id: uuid.UUID,
    body: BuyerIn,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """A business customer comes back for an invoice with their PIN on it:
    add it before the sale is filed."""
    inv = await _owned(session, principal, invoice_id)
    if inv.etims_status == "submitted":
        raise HTTPException(409, "already filed with KRA; issue a credit note and a new invoice to change the buyer")
    pin = normalize_pin(body.pin)
    if pin and not is_kra_pin(pin):
        raise HTTPException(422, "a KRA PIN looks like P051234567X: A or P, nine digits, a letter")
    inv.buyer_pin = pin
    inv.buyer_name = body.name.strip()
    await session.commit()
    cfg = await get_etims_config(principal.org_id)
    return _row(inv, cfg, await _originals(session, _org(principal), [inv]))


@router.get("/pin/{pin}")
async def check_pin(pin: str, principal: Principal = Depends(get_current_principal)):
    """A buyer's KRA PIN: always the format; with automation on, also who
    KRA says it belongs to (/selectCustomer). Without it, the till offers
    KRA's own PIN checker."""
    p = normalize_pin(pin)
    out = {"pin": p, "format_ok": is_kra_pin(p), "verified": None, "name": "", "active": None, "checker_url": PIN_CHECKER_URL}
    if not out["format_ok"] or not automation_on():
        return out
    cfg = await get_etims_config(principal.org_id)
    if not cfg.get("enabled") or not cfg.get("cmc_key"):
        return out
    try:
        found = await OscuClient(EtimsConfig.from_kernel(cfg)).lookup_customer(p)
    except EtimsError:
        return out  # KRA unreachable: the sale goes on; the PIN is checked when filed
    out["verified"] = found is not None
    if found:
        out["name"] = found.get("taxprNm", "")
        out["active"] = found.get("taxprSttsCd") == "A"
    return out


@router.get("/vat-sales.csv")
async def vat_sales_csv(
    month: str,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """The month's sales by tax type, in the columns of the iTax VAT3
    sales schedule (Section B). iTax now pre-fills sales from eTIMS; this
    is the business's own copy to check it against."""
    bounds = _month_bounds(month)
    assert bounds
    org = _org(principal)
    when = func.coalesce(Invoice.issued_at, Invoice.created_at)
    invs = (
        await session.execute(
            select(Invoice).where(Invoice.org_id == org, _in_scope(), when >= bounds[0], when < bounds[1]).order_by(when)
        )
    ).scalars().all()
    cfg = await get_etims_config(principal.org_id)
    originals = await _originals(session, org, invs)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "PIN of Purchaser",
            "Name of Purchaser",
            "ETR Serial Number",
            "Invoice Date",
            "Invoice Number",
            "Description of Goods / Services",
            "Tax Type",
            "Taxable Value (Ksh)",
            "Amount of VAT (Ksh)",
            "Relevant Invoice Number",
            "Relevant Invoice Date",
        ]
    )
    for inv in invs:
        row = _row(inv, cfg, originals)
        orig = originals.get(inv.source_ref or "") if row.credit_note else None
        sign = -1 if row.credit_note else 1
        for code, amt in sorted(row.by_code.items()):
            taxable = (amt["gross_cents"] - amt["vat_cents"]) * sign
            w.writerow(
                [
                    inv.buyer_pin,
                    inv.buyer_name,
                    cfg.get("device_serial", ""),
                    (row.issued_at or inv.created_at).strftime("%d/%m/%Y"),
                    inv.etims_invoice_no or inv.number,
                    "Goods sold" if inv.source == "pos" else "Sales",
                    code,
                    f"{taxable / 100:.2f}",
                    f"{amt['vat_cents'] * sign / 100:.2f}",
                    (orig.etims_invoice_no or orig.number) if orig else "",
                    (orig.issued_at or orig.created_at).strftime("%d/%m/%Y") if orig else "",
                ]
            )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="vat-sales-{month}.csv"'},
    )


async def _next_trader_no(session: AsyncSession, org: uuid.UUID) -> int:
    row = await session.execute(
        text(
            """
            INSERT INTO etims_sequences (org_id, last_no) VALUES (:org, 1)
            ON CONFLICT (org_id) DO UPDATE SET last_no = etims_sequences.last_no + 1
            RETURNING last_no
            """
        ),
        {"org": org},
    )
    return int(row.scalar_one())


async def send_unfiled(session: AsyncSession, org: uuid.UUID, cfg: dict, client: OscuClient, limit: int = 50) -> dict:
    """Sends unfiled sales (oldest first) and then credit notes to KRA,
    recording what KRA answers. A sale KRA refuses is marked failed with
    KRA's message and tried again on the next run (attempts counts)."""
    invs = (
        await session.execute(
            select(Invoice)
            .where(Invoice.org_id == org, _in_scope(), Invoice.etims_status.in_(("unfiled", "failed")))
            .order_by(func.coalesce(Invoice.issued_at, Invoice.created_at))
            .limit(limit)
        )
    ).scalars().all()
    sent = failed = 0
    for inv in invs:
        await session.refresh(inv, attribute_names=["lines", "payments"])
        credit_of = 0
        if is_credit_note(inv):
            orig = (await _originals(session, org, [inv])).get(inv.source_ref or "")
            if orig is None or orig.etims_status != "submitted" or not orig.etims_trader_no:
                continue  # the sale goes first
            credit_of = orig.etims_trader_no
        if inv.etims_trader_no is None:
            inv.etims_trader_no = await _next_trader_no(session, org)
            await session.commit()
        doc = document_for(inv, cfg, credit_note_of=credit_of)
        inv.etims_attempts += 1
        try:
            res = await client.save_sale(sale_body(doc))
        except EtimsError as exc:
            inv.etims_status = "failed"
            inv.etims_error = str(exc)[:500]
            failed += 1
        else:
            inv.etims_status = "submitted"
            inv.etims_via = cfg.get("mode") or "oscu"
            inv.etims_invoice_no = f"{res.get('curRcptNo', '')}/{res.get('totRcptNo', '')}".strip("/")
            inv.etims_receipt_sign = str(res.get("rcptSign", ""))
            inv.etims_internal_data = str(res.get("intrlData", ""))
            inv.etims_sdc_time = str(res.get("sdcDateTime", ""))
            inv.etims_filed_at = datetime.now(UTC)
            inv.etims_filed_by = "eTIMS (automatic)"
            inv.etims_error = ""
            sent += 1
        await session.commit()
    return {"sent": sent, "failed": failed}


@router.post("/send")
async def send_now(
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """Send unfiled sales to KRA now. Refused until this server has
    automation switched on and the org has turned eTIMS on."""
    if not automation_on():
        raise HTTPException(409, "automatic sending is not switched on for this server yet; file sales in the eTIMS portal")
    cfg = await get_etims_config(principal.org_id)
    if not cfg.get("enabled") or not cfg.get("cmc_key"):
        raise HTTPException(409, "turn eTIMS on and add the CMC key in Business settings first")
    return await send_unfiled(session, _org(principal), cfg, OscuClient(EtimsConfig.from_kernel(cfg)))
