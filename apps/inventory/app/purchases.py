"""Purchases and VAT (owner, 2026-11-16).

When goods are received, each purchase order line's VAT is worked out
from its tax type (the product's, else the business default) and the
business's rates, on the cost before VAT. Then:
- inventory.purchase.received goes to Accounting (Dr Inventory, Dr VAT
  Input, Cr Accounts Payable);
- GET /purchase_orders/vat-purchases.csv lists the month's purchases in
  the columns of the iTax VAT3 purchases schedule (Section F), for the
  business to upload with its return.
"""

import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from friday_common import Principal, get_org_session, publish_event
from friday_common.auth import require_role
from friday_common.etims.codes import TAX_TYPES
from friday_common.etims.kernel import get_etims_config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Product, PurchaseOrder, Supplier

router = APIRouter(prefix="/purchase_orders", tags=["purchases"])


async def _rates(org_id: str) -> tuple[dict[str, int], str, bool]:
    """Rates in basis points per tax type, the default type, and whether
    the business is VAT-registered (one that isn't claims no input VAT)."""
    cfg = await get_etims_config(org_id)
    rates = {c: pct * 100 for c, (_, pct) in TAX_TYPES.items()}
    for r in cfg.get("rates") or []:
        rates[r["code"]] = int(r["rate_bp"])
    return rates, cfg.get("default_code") or "B", cfg.get("vat_registered", True)


async def price_purchase_vat(session: AsyncSession, org_id: str, po: PurchaseOrder) -> None:
    rates, default, registered = await _rates(org_id)
    for line in po.lines:
        code = line.tax_code
        if not code and line.product_id:
            product = await session.get(Product, line.product_id)
            code = product.tax_code if product else ""
        line.tax_code = code or default
        net = Decimal(line.quantity) * line.unit_cost_cents
        rate = rates.get(line.tax_code, 0) if registered else 0
        line.vat_cents = int((net * rate / 10_000).quantize(Decimal(1), rounding=ROUND_HALF_UP))


async def publish_purchase_received(session: AsyncSession, org_id: str, po: PurchaseOrder) -> None:
    supplier = await session.get(Supplier, po.supplier_id) if po.supplier_id else None
    net = sum(line.total_cost_cents for line in po.lines)
    vat = sum(line.vat_cents for line in po.lines)
    await publish_event(
        "inventory.purchase.received",
        org_id,
        {
            "purchase_order_id": str(po.id),
            "po_number": po.number,
            "supplier_name": supplier.name if supplier else "",
            "supplier_pin": supplier.kra_pin if supplier else "",
            "supplier_invoice_no": po.supplier_invoice_no,
            "net_cents": net,
            "vat_cents": vat,
        },
    )


@router.get("/vat-purchases.csv")
async def vat_purchases_csv(
    month: str,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """The month's received purchases in the columns of the iTax VAT3
    purchases schedule (Section F), one row per supplier invoice and tax
    type. Purchases without a supplier PIN are listed too, marked, since
    KRA only allows input VAT backed by the supplier's PIN and invoice."""
    try:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    except ValueError:
        raise HTTPException(422, "month is YYYY-MM") from None
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    org = uuid.UUID(principal.org_id)
    pos = (
        await session.execute(
            select(PurchaseOrder)
            .where(PurchaseOrder.org_id == org, PurchaseOrder.received_at >= start, PurchaseOrder.received_at < end)
            .order_by(PurchaseOrder.received_at)
        )
    ).scalars().all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "Type of Purchases",
            "PIN of Supplier",
            "Name of Supplier",
            "Invoice Date",
            "Invoice Number",
            "Description of Goods / Services",
            "Custom Entry Number",
            "Tax Type",
            "Taxable Value (Ksh)",
            "Amount of VAT (Ksh)",
            "Relevant Invoice Number",
            "Relevant Invoice Date",
            "Note",
        ]
    )
    for po in pos:
        await session.refresh(po, attribute_names=["lines"])
        supplier = await session.get(Supplier, po.supplier_id) if po.supplier_id else None
        by_code: dict[str, list[int]] = {}
        for line in po.lines:
            row = by_code.setdefault(line.tax_code or "B", [0, 0])
            row[0] += line.total_cost_cents
            row[1] += line.vat_cents
        when = po.supplier_invoice_date or (po.received_at or po.updated_at).date()
        note = []
        if not (supplier and supplier.kra_pin):
            note.append("no supplier PIN")
        if not po.supplier_invoice_no:
            note.append("no supplier invoice number")
        for code, (net, vat) in sorted(by_code.items()):
            w.writerow(
                [
                    "Local",
                    supplier.kra_pin if supplier else "",
                    supplier.name if supplier else "",
                    when.strftime("%d/%m/%Y"),
                    po.supplier_invoice_no or po.number,
                    "Goods for resale",
                    "",
                    code,
                    f"{net / 100:.2f}",
                    f"{vat / 100:.2f}",
                    "",
                    "",
                    "; ".join(note),
                ]
            )
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="vat-purchases-{month}.csv"'},
    )
