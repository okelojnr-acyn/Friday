"""Inbound webhooks Accounting subscribes to (see
kernel/internal/gateway/events.go) -- this is what turns Invoicing/POS
activity into the ledger automatically, cash-basis only (an entry is
posted when money actually moves, never on invoice-issue).

A standalone module, not part of main.py, for the same reason
invoicing/app/events.py is standalone: keeps the auto-posting logic
(and its own helpers) out of the resource-CRUD file.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from friday_common import first_delivery, get_session, require_kernel_token, set_org_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .accounts import ensure_default_accounts, get_account_by_code
from .models import JournalEntry, JournalLine

webhooks_router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])

# Payment method -> the account the money lands in.
MONEY_ACCOUNT = {
    "cash": "1010",
    "refund": "1010",  # a till refund comes out of the drawer
    "pos": "1010",
    "mpesa": "1020",
    "pesapal": "1020",
    "airtel": "1020",
    "card": "1030",
    "bank_transfer": "1030",
    "bank": "1030",
    "stripe": "1030",
}


async def _already_posted(session: AsyncSession, org_id: uuid.UUID, source: str, source_ref: str) -> bool:
    """Webhook delivery is at-least-once (kernel/internal/gateway/events.go's
    forward() doesn't dedupe), so every auto-posting webhook here must be
    idempotent on replay -- checked by (org_id, source, source_ref) rather
    than a DB unique constraint, same "enforce it in code, not the
    database" rule as everywhere else in this app."""
    rows = await session.execute(
        select(JournalEntry.id).where(
            JournalEntry.org_id == org_id,
            JournalEntry.source == source,
            JournalEntry.source_ref == source_ref,
        )
    )
    return rows.first() is not None


def _new_entry_number(now: datetime) -> str:
    return f"JE-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}"


@webhooks_router.post("/invoice-paid", dependencies=[Depends(require_kernel_token)], status_code=204)
async def invoice_paid(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to invoicing.invoice.paid -- posts the cash-basis entry
    the moment an invoice is actually paid: Dr Cash / Cr Revenue / Cr Tax
    Payable. A negative amount (a POS return or a credit note) mirrors
    the debit/credit sides instead of going negative, so the ledger never
    carries a negative entry."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    # The kernel retries until a delivery succeeds; a repeat is skipped.
    if not await first_delivery(session, body):
        return

    invoice_id = payload.get("invoice_id") or ""
    if invoice_id and await _already_posted(session, org_id, "invoicing", invoice_id):
        return

    subtotal_cents = payload.get("subtotal_cents", 0) or 0
    tax_cents = payload.get("tax_cents", 0) or 0
    amount_cents = subtotal_cents + tax_cents
    if amount_cents == 0:
        return
    # The VAT inside the amount (Invoicing works it out per line, prices
    # with VAT inside or not). Revenue is the amount less VAT. An event
    # from before 2026-11-16 has no vat_cents: its tax_cents was the VAT.
    vat_cents = payload.get("vat_cents")
    if vat_cents is None:
        vat_cents = tax_cents
    net_cents = amount_cents - vat_cents

    await ensure_default_accounts(session, org_id)
    revenue = await get_account_by_code(session, org_id, "4000")
    tax_payable = await get_account_by_code(session, org_id, "2200")
    # Where the money went: one debit (or credit, for a refund) per
    # payment method, when the payments add up to the amount.
    payments = payload.get("payments") or []
    if not payments or sum(int(p.get("amount_cents", 0)) for p in payments) != amount_cents:
        payments = [{"method": "cash", "amount_cents": amount_cents}]
    money: dict[str, int] = {}
    for p in payments:
        code = MONEY_ACCOUNT.get(p.get("method", ""), "1010")
        money[code] = money.get(code, 0) + int(p.get("amount_cents", 0))

    now = datetime.now(UTC)
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=now.date(),
        memo=f"Invoice {payload.get('invoice_number', '')} paid",
        source="invoicing",
        source_ref=invoice_id,
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()

    cash_is_debit = amount_cents > 0
    for code, cents in money.items():
        if not cents:
            continue
        account = await get_account_by_code(session, org_id, code)
        session.add(
            JournalLine(
                org_id=org_id,
                journal_entry_id=entry.id,
                account_id=account.id,
                debit_cents=cents if cents > 0 else 0,
                credit_cents=-cents if cents < 0 else 0,
                description=("Received" if cents > 0 else "Refunded") + f" ({account.name})",
            )
        )
    if net_cents:
        session.add(
            JournalLine(
                org_id=org_id,
                journal_entry_id=entry.id,
                account_id=revenue.id,
                debit_cents=0 if cash_is_debit else abs(net_cents),
                credit_cents=abs(net_cents) if cash_is_debit else 0,
                description="Sales revenue (excl. VAT)" if cash_is_debit else "Sales revenue reversal",
            )
        )
    if vat_cents:
        session.add(
            JournalLine(
                org_id=org_id,
                journal_entry_id=entry.id,
                account_id=tax_payable.id,
                debit_cents=0 if cash_is_debit else abs(vat_cents),
                credit_cents=abs(vat_cents) if cash_is_debit else 0,
                description="VAT on sales" if cash_is_debit else "VAT on sales reversal",
            )
        )
    await session.commit()


@webhooks_router.post("/purchase-received", dependencies=[Depends(require_kernel_token)], status_code=204)
async def purchase_received(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to inventory.purchase.received: goods in from a supplier.
    Dr Inventory Asset (cost excl. VAT), Dr VAT Input (the VAT charged,
    claimable on the VAT return), Cr Accounts Payable (what is owed). Paying
    the supplier is booked when it happens (a manual entry for now)."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    if not await first_delivery(session, body):
        return
    ref = payload.get("purchase_order_id") or ""
    if ref and await _already_posted(session, org_id, "inventory", ref):
        return
    net_cents = int(payload.get("net_cents", 0) or 0)
    vat_cents = int(payload.get("vat_cents", 0) or 0)
    if net_cents == 0 and vat_cents == 0:
        return

    await ensure_default_accounts(session, org_id)
    inventory_asset = await get_account_by_code(session, org_id, "1400")
    vat_input = await get_account_by_code(session, org_id, "1500")
    payable = await get_account_by_code(session, org_id, "2000")

    now = datetime.now(UTC)
    supplier = payload.get("supplier_name") or "supplier"
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=now.date(),
        memo=f"Goods received {payload.get('po_number', '')} from {supplier}"
        + (f", invoice {payload['supplier_invoice_no']}" if payload.get("supplier_invoice_no") else ""),
        source="inventory",
        source_ref=ref,
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()
    session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=inventory_asset.id, debit_cents=net_cents, credit_cents=0, description="Stock received (excl. VAT)"))
    if vat_cents:
        session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=vat_input.id, debit_cents=vat_cents, credit_cents=0, description="VAT on purchases"))
    session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=payable.id, debit_cents=0, credit_cents=net_cents + vat_cents, description=f"Owed to {supplier}"))
    await session.commit()


@webhooks_router.post("/pos-sale-cogs", dependencies=[Depends(require_kernel_token)], status_code=204)
async def pos_sale_cogs(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to invoicing.pos_sale.recorded -- posts Dr COGS / Cr
    Inventory Asset for every line that carries unit_cost_cents (set when
    a POS line was rung up from the product catalog with a known cost).
    Lines without it -- a manual/freeform invoice, or before POS threaded
    cost through -- are a documented gap: there's no cost to post against,
    not a bug. A return's negative quantities flow through unchanged and
    naturally reverse the entry (Cr COGS / Dr Inventory)."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    # The kernel retries until a delivery succeeds; a repeat is skipped.
    if not await first_delivery(session, body):
        return

    invoice_number = payload.get("invoice_number") or ""
    if invoice_number and await _already_posted(session, org_id, "pos", invoice_number):
        return

    cogs_cents = 0
    for line in payload.get("lines", []):
        unit_cost_cents = line.get("unit_cost_cents")
        if unit_cost_cents is None:
            continue
        cogs_cents += round(unit_cost_cents * line.get("quantity", 0))
    if cogs_cents == 0:
        return

    await ensure_default_accounts(session, org_id)
    cogs = await get_account_by_code(session, org_id, "5000")
    inventory_asset = await get_account_by_code(session, org_id, "1400")

    now = datetime.now(UTC)
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=now.date(),
        memo=f"Cost of goods sold for {invoice_number}",
        source="pos",
        source_ref=invoice_number,
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()

    cogs_is_debit = cogs_cents > 0
    session.add(
        JournalLine(
            org_id=org_id,
            journal_entry_id=entry.id,
            account_id=cogs.id,
            debit_cents=abs(cogs_cents) if cogs_is_debit else 0,
            credit_cents=0 if cogs_is_debit else abs(cogs_cents),
            description="Cost of goods sold" if cogs_is_debit else "Cost of goods sold reversal",
        )
    )
    session.add(
        JournalLine(
            org_id=org_id,
            journal_entry_id=entry.id,
            account_id=inventory_asset.id,
            debit_cents=0 if cogs_is_debit else abs(cogs_cents),
            credit_cents=abs(cogs_cents) if cogs_is_debit else 0,
            description="Inventory consumed" if cogs_is_debit else "Inventory restored",
        )
    )
    await session.commit()


@webhooks_router.post("/payroll-paid", dependencies=[Depends(require_kernel_token)], status_code=204)
async def payroll_paid(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to minions.payroll_run.paid -- posts Dr Salary Expense /
    Cr Cash for the amount actually paid out (Minions only publishes this
    once every line in the run has reached a terminal state, and only
    counts lines that were actually confirmed -- blocked/failed lines
    never moved money, see apps/minions/app/main.py's
    refresh_payroll_run_status)."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    # The kernel retries until a delivery succeeds; a repeat is skipped.
    if not await first_delivery(session, body):
        return

    payroll_run_id = payload.get("payroll_run_id") or ""
    if payroll_run_id and await _already_posted(session, org_id, "payroll", payroll_run_id):
        return

    amount_cents = payload.get("amount_cents", 0) or 0
    if amount_cents <= 0:
        return

    await ensure_default_accounts(session, org_id)
    salary_expense = await get_account_by_code(session, org_id, "6000")
    cash = await get_account_by_code(session, org_id, "1010")

    now = datetime.now(UTC)
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=now.date(),
        memo=f"Payroll run {payroll_run_id} paid",
        source="payroll",
        source_ref=payroll_run_id,
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()

    session.add(
        JournalLine(
            org_id=org_id,
            journal_entry_id=entry.id,
            account_id=salary_expense.id,
            debit_cents=amount_cents,
            credit_cents=0,
            description="Salary expense",
        )
    )
    session.add(
        JournalLine(
            org_id=org_id,
            journal_entry_id=entry.id,
            account_id=cash.id,
            debit_cents=0,
            credit_cents=amount_cents,
            description="Cash paid out",
        )
    )
    await session.commit()
