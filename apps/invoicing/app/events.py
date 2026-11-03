"""Publishes invoicing.invoice.paid -- the event Accounting (see
kernel/internal/gateway/events.go) subscribes to in order to post a
cash-basis journal entry (Dr Cash / Cr Revenue / Cr Tax Payable) the
moment an invoice is actually paid.

A standalone module, not part of main.py, because this needs to be
called from both main.py (record_payment, record_pos_sale,
return_pos_sale) and webhooks.py (the Stripe webhook) -- and main.py
already imports webhooks.py's routers, so webhooks.py importing back
from main.py would be circular.
"""

from __future__ import annotations

from friday_common import publish_event

from .models import Invoice


def invoice_lines_payload(inv: Invoice) -> list[dict]:
    """unit_cost_cents is always None for now -- POS doesn't thread
    product cost through the sale payload yet. Once it does, Accounting's
    pos-sale-cogs webhook will post COGS/Inventory-Asset entries only for
    lines where this isn't None; until then that's a documented gap, not
    a bug."""
    return [
        {
            "description": line.description,
            "quantity": float(line.quantity),
            "unit_price_cents": line.unit_price_cents,
            "product_id": str(line.product_id) if line.product_id else None,
            "unit_cost_cents": None,
        }
        for line in inv.lines
    ]


async def publish_invoice_paid(org_id: str, inv: Invoice, paid_amount_cents: int, lines_payload: list[dict]) -> None:
    subtotal_cents = sum(line.total_cents for line in inv.lines)
    tax_cents = sum(line.tax_cents for line in inv.lines)
    await publish_event(
        "invoicing.invoice.paid",
        org_id,
        {
            "invoice_id": str(inv.id),
            "invoice_number": inv.number,
            "customer_id": str(inv.customer_id) if inv.customer_id else None,
            "source": inv.source,
            "currency": inv.currency,
            "subtotal_cents": subtotal_cents,
            "tax_cents": tax_cents,
            "paid_amount_cents": paid_amount_cents,
            "lines": lines_payload,
        },
    )
