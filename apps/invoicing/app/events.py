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
                    # Base units per sold unit; Inventory multiplies.
                    **({"uom_factor": float(line.uom_factor)} if line.uom_factor is not None else {}),
                }
                for line in inv.lines
                if line.product_id
            ],
        },
    )


def vat_of(inv: Invoice) -> tuple[int, dict[str, int]]:
    """The VAT in a document and per eTIMS tax type: what the till worked
    out per line (vat_cents), or a typed invoice's own per-line tax. The
    till's reconciling line is not an item and carries none. Code "" is
    the business's default rate."""
    by_code: dict[str, int] = {}
    for line in inv.lines:
        if line.is_adjustment:
            continue
        vat = line.vat_cents or (line.tax_cents if line.tax_rate_bp else 0)
        by_code[line.tax_code or ""] = by_code.get(line.tax_code or "", 0) + vat
    return sum(by_code.values()), by_code


async def publish_invoice_paid(
    org_id: str,
    inv: Invoice,
    paid_amount_cents: int,
    lines_payload: list[dict],
    *,
    posting_ref: str | None = None,
    sign: int = 1,
    payments: list | None = None,
) -> None:
    """sign=-1 publishes the exact mirror of an earlier booking (a reversed
    payment), with `payments` as they were when it was booked. posting_ref
    tells Accounting this is a separate posting from the invoice's first."""
    subtotal_cents = sign * sum(line.total_cents for line in inv.lines)
    tax_cents = sign * sum(line.tax_cents for line in inv.lines)
    vat_cents, vat_by_code = vat_of(inv)
    vat_cents *= sign
    vat_by_code = {k: sign * v for k, v in vat_by_code.items()}
    paid = inv.payments if payments is None else payments
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
            # VAT inside the amount (subtotal + tax), whether the prices
            # included it or not: Accounting books revenue net of it.
            "vat_cents": vat_cents,
            "vat_by_code": vat_by_code,
            # How it was paid, so M-Pesa and card don't land in the drawer.
            "payments": [{"method": p.method, "amount_cents": sign * p.amount_cents} for p in paid],
            "lines": lines_payload,
            **({"posting_ref": posting_ref} if posting_ref else {}),
        },
    )
