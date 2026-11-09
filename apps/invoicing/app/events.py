"""Publishes invoicing.invoice.paid and invoicing.pos_sale.recorded --
events Accounting/Inventory/Minions (see kernel/internal/gateway/events.go)
subscribe to.

A standalone module, not part of main.py, because this needs to be
called from both main.py (record_payment, record_pos_sale,
return_pos_sale, pay_with_pesapal) and webhooks.py (the Stripe/Pesapal
webhooks) -- and main.py already imports webhooks.py's routers, so
webhooks.py importing back from main.py would be circular.
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


async def publish_pos_sale_recorded(org_id: str, inv: Invoice, charged_cents: int) -> None:
    """Shared by record_pos_sale, return_pos_sale, and pay_with_pesapal's
    webhook confirmation -- previously built inline at each call site
    (slightly differently: record_pos_sale read raw client-supplied
    lines, return_pos_sale read committed InvoiceLine rows), which is how
    cashier identity would have had to be threaded through three times.
    Building it once from `inv.lines` (always committed/refreshed by the
    time any caller publishes) fixes that drift as a side effect, not
    just avoids repeating it. Lets Inventory auto-decrement stock and
    Minions attribute the sale to an employee, both via product_id/
    cashier_user_id -- freeform/ad-hoc lines with no product_id are
    skipped on the subscriber side, same as before."""
    await publish_event(
        "invoicing.pos_sale.recorded",
        org_id,
        {
            "invoice_number": inv.number,
            "amount_cents": charged_cents,
            "cashier_user_id": inv.cashier_user_id,
            "cashier_email": inv.cashier_email,
            "lines": [
                {
                    "product_id": str(line.product_id),
                    "quantity": float(line.quantity),
                    "unit_cost_cents": line.unit_cost_cents,
                }
                for line in inv.lines
                if line.product_id
            ],
        },
    )


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
