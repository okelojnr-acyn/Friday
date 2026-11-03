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
from friday_common import get_session, require_kernel_token, set_org_context
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .accounts import ensure_default_accounts, get_account_by_code
from .models import JournalEntry, JournalLine

webhooks_router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])


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

    invoice_id = payload.get("invoice_id") or ""
    if invoice_id and await _already_posted(session, org_id, "invoicing", invoice_id):
        return

    subtotal_cents = payload.get("subtotal_cents", 0) or 0
    tax_cents = payload.get("tax_cents", 0) or 0
    amount_cents = subtotal_cents + tax_cents
    if amount_cents == 0:
        return

    await ensure_default_accounts(session, org_id)
    cash = await get_account_by_code(session, org_id, "1010")
    revenue = await get_account_by_code(session, org_id, "4000")
    tax_payable = await get_account_by_code(session, org_id, "2200")

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
    session.add(
        JournalLine(
            org_id=org_id,
            journal_entry_id=entry.id,
            account_id=cash.id,
            debit_cents=abs(amount_cents) if cash_is_debit else 0,
            credit_cents=0 if cash_is_debit else abs(amount_cents),
            description="Cash received" if cash_is_debit else "Cash refunded",
        )
    )
    if subtotal_cents:
        session.add(
            JournalLine(
                org_id=org_id,
                journal_entry_id=entry.id,
                account_id=revenue.id,
                debit_cents=0 if cash_is_debit else abs(subtotal_cents),
                credit_cents=abs(subtotal_cents) if cash_is_debit else 0,
                description="Sales revenue" if cash_is_debit else "Sales revenue reversal",
            )
        )
    if tax_cents:
        session.add(
            JournalLine(
                org_id=org_id,
                journal_entry_id=entry.id,
                account_id=tax_payable.id,
                debit_cents=0 if cash_is_debit else abs(tax_cents),
                credit_cents=abs(tax_cents) if cash_is_debit else 0,
                description="Sales tax payable" if cash_is_debit else "Sales tax payable reversal",
            )
        )
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
