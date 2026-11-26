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
from friday_common.clock import business_tz, local_date
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
    "cheque": "1030",
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
    # One booking per posting: normally the invoice itself; a reversed
    # payment and a later re-payment each come with their own ref, so an
    # invoice that becomes unpaid and is paid again is booked again.
    posting_ref = payload.get("posting_ref") or invoice_id
    if posting_ref and await _already_posted(session, org_id, "invoicing", posting_ref):
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

    await ensure_default_accounts(session, org_id, commit=False)
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
        entry_date=local_date(now, await business_tz(str(org_id))),
        memo=f"Invoice {payload.get('invoice_number', '')} paid",
        source="invoicing",
        source_ref=posting_ref,
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

    await ensure_default_accounts(session, org_id, commit=False)
    inventory_asset = await get_account_by_code(session, org_id, "1400")
    vat_input = await get_account_by_code(session, org_id, "1500")
    payable = await get_account_by_code(session, org_id, "2000")

    now = datetime.now(UTC)
    supplier = payload.get("supplier_name") or "supplier"
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=local_date(now, await business_tz(str(org_id))),
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


@webhooks_router.post("/stock-adjusted", dependencies=[Depends(require_kernel_token)], status_code=204)
async def stock_adjusted(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to inventory.stock.adjusted: stock counted in or out by
    hand, at cost. In: Dr Inventory Asset, Cr Owner's Equity (stock put
    into the business without a purchase order). Out: Dr Stock losses,
    Cr Inventory Asset (plan 20.2 #1)."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    if not await first_delivery(session, body):
        return
    value = int(payload.get("value_cents", 0) or 0)
    if value == 0:
        return
    await ensure_default_accounts(session, org_id, commit=False)
    inventory_asset = await get_account_by_code(session, org_id, "1400")
    other = await get_account_by_code(session, org_id, "3000" if value > 0 else "5100")
    now = datetime.now(UTC)
    name = payload.get("product_name") or "stock"
    word = "in" if value > 0 else "out"
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=local_date(now, await business_tz(str(org_id))),
        memo=f"Stock counted {word}: {abs(payload.get('delta', 0)):g} {name}"
        + (f" ({payload['reference']})" if payload.get("reference") else ""),
        source="inventory",
        source_ref=str(body.get("id") or ""),
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()
    amount = abs(value)
    debit, credit = (inventory_asset, other) if value > 0 else (other, inventory_asset)
    session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=debit.id, debit_cents=amount, credit_cents=0, description=f"{name}, at cost"))
    session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=credit.id, debit_cents=0, credit_cents=amount, description=f"{name}, at cost"))
    await session.commit()


@webhooks_router.post("/purchase-paid", dependencies=[Depends(require_kernel_token)], status_code=204)
async def purchase_paid(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to inventory.purchase.paid: the supplier is paid.
    Dr Accounts Payable, Cr the account the money left from (cash, M-Pesa,
    card and bank), so the payable goes back to zero."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    if not await first_delivery(session, body):
        return
    ref = "paid:" + (payload.get("purchase_order_id") or "")
    if await _already_posted(session, org_id, "inventory", ref):
        return
    amount_cents = int(payload.get("amount_cents", 0) or 0)
    if amount_cents <= 0:
        return

    await ensure_default_accounts(session, org_id, commit=False)
    payable = await get_account_by_code(session, org_id, "2000")
    money = await get_account_by_code(session, org_id, MONEY_ACCOUNT.get(payload.get("method", ""), "1010"))

    now = datetime.now(UTC)
    supplier = payload.get("supplier_name") or "supplier"
    memo = f"Paid {supplier} for {payload.get('po_number', '')}"
    if payload.get("reference"):
        memo += f" ({payload['reference']})"
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=local_date(now, await business_tz(str(org_id))),
        memo=memo,
        source="inventory",
        source_ref=ref,
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()
    session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=payable.id, debit_cents=amount_cents, credit_cents=0, description=f"Paid {supplier}"))
    session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=money.id, debit_cents=0, credit_cents=amount_cents, description=f"Paid out ({money.name})"))
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

    await ensure_default_accounts(session, org_id, commit=False)
    cogs = await get_account_by_code(session, org_id, "5000")
    inventory_asset = await get_account_by_code(session, org_id, "1400")

    now = datetime.now(UTC)
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=local_date(now, await business_tz(str(org_id))),
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


@webhooks_router.post("/claim-paid", dependencies=[Depends(require_kernel_token)], status_code=204)
async def claim_paid(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to minions.expense_claim.paid: Cr the account it was paid
    from (M-Pesa, bank, else Cash), Dr 2150 Owed to staff when Guss already booked the expense as
    owed (owed_booked), else Dr 6900 Shop expenses (booked now)."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    if not await first_delivery(session, body):
        return
    claim_id = payload.get("claim_id") or ""
    if claim_id and await _already_posted(session, org_id, "claim", claim_id):
        return
    amount_cents = payload.get("amount_cents", 0) or 0
    if amount_cents <= 0:
        return
    await ensure_default_accounts(session, org_id, commit=False)
    debit = await get_account_by_code(session, org_id, "2150" if payload.get("owed_booked") else "6900")
    cash = await get_account_by_code(session, org_id, MONEY_ACCOUNT.get(payload.get("method") or "cash", "1010"))
    now = datetime.now(UTC)
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=local_date(now, await business_tz(str(org_id))),
        memo=f"Expense claim paid: {payload.get('description') or claim_id}"[:500],
        source="claim",
        source_ref=claim_id,
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()
    session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=debit.id, debit_cents=amount_cents, credit_cents=0, description=debit.name))
    session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=cash.id, debit_cents=0, credit_cents=amount_cents, description="Paid out"))
    await session.commit()


@webhooks_router.post("/advance-paid", dependencies=[Depends(require_kernel_token)], status_code=204)
async def advance_paid(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to minions.salary_advance.paid: Dr 1210 Staff advances,
    Cr the account it was paid from (M-Pesa, bank, else cash). Payroll
    credits 1210 back as it's recovered."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    if not await first_delivery(session, body):
        return
    advance_id = payload.get("advance_id") or ""
    if advance_id and await _already_posted(session, org_id, "advance", advance_id):
        return
    amount_cents = int(payload.get("amount_cents") or 0)
    if amount_cents <= 0:
        return
    await ensure_default_accounts(session, org_id, commit=False)
    advances = await get_account_by_code(session, org_id, "1210")
    money = await get_account_by_code(session, org_id, MONEY_ACCOUNT.get(payload.get("method") or "cash", "1010"))
    now = datetime.now(UTC)
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=local_date(now, await business_tz(str(org_id))),
        memo=(payload.get("description") or f"Salary advance {advance_id} paid")[:500],
        source="advance",
        source_ref=advance_id,
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()
    for account, debit, credit, description in (
        (advances, amount_cents, 0, "Salary advance (owed by staff)"),
        (money, 0, amount_cents, "Advance paid out"),
    ):
        session.add(
            JournalLine(
                org_id=org_id,
                journal_entry_id=entry.id,
                account_id=account.id,
                debit_cents=debit,
                credit_cents=credit,
                description=description,
            )
        )
    await session.commit()


@webhooks_router.post("/trip-settled", dependencies=[Depends(require_kernel_token)], status_code=204)
async def trip_settled(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to minions.trip.settled: the trip's spends become 6900
    Shop expenses against 1210 Staff advances (its cash up front). What
    was left and given back goes into the money it came back as; an
    overspend paid to the person comes out of it; left and taken off pay
    ("payroll") stays in 1210 until payroll recovers it."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    if not await first_delivery(session, body):
        return
    request_id = payload.get("request_id") or ""
    if request_id and await _already_posted(session, org_id, "trip", request_id):
        return
    advance, spent = int(payload.get("advance_cents") or 0), int(payload.get("spent_cents") or 0)
    method = payload.get("method") or "cash"
    balance = advance - spent  # > 0 given back (or off pay); < 0 paid to them
    staff_credit = spent if method == "payroll" and balance > 0 else advance
    await ensure_default_accounts(session, org_id, commit=False)
    expenses = await get_account_by_code(session, org_id, "6900")
    advances = await get_account_by_code(session, org_id, "1210")
    money = await get_account_by_code(session, org_id, MONEY_ACCOUNT.get(method, "1010"))
    lines = [(expenses, spent, 0, "Trip spends"), (advances, 0, staff_credit, "Trip advance settled")]
    if balance > 0 and method != "payroll":
        lines.append((money, balance, 0, "Unused advance given back"))
    elif balance < 0:
        lines.append((money, 0, -balance, "Overspend paid to staff"))
    lines = [line for line in lines if line[1] or line[2]]
    if not lines:
        return
    now = datetime.now(UTC)
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=local_date(now, await business_tz(str(org_id))),
        memo=f"Trip settled: {payload.get('description') or request_id}"[:500],
        source="trip",
        source_ref=request_id,
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()
    for account, debit, credit, description in lines:
        session.add(JournalLine(org_id=org_id, journal_entry_id=entry.id, account_id=account.id,
                                debit_cents=debit, credit_cents=credit, description=description))
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

    await ensure_default_accounts(session, org_id, commit=False)
    # (account, debit, credit, description). With a payslip breakdown
    # (Minions 0009): Dr salaries (gross) and the employer's share, Cr cash
    # (net) and what's owed to KRA, NSSF and SHA. Older events: gross = paid.
    p = lambda k: int(payload.get(k) or 0)  # noqa: E731
    if p("gross_cents"):
        employer = p("employer_nssf_cents") + p("employer_levy_cents")
        legs = [
            ("6000", p("gross_cents"), 0, "Salaries (gross)"),
            ("6010", employer, 0, "Employer NSSF and Housing Levy"),
            ("1010", 0, amount_cents, "Net pay paid out"),
            ("2310", 0, p("paye_cents"), "PAYE withheld"),
            ("2320", 0, p("nssf_cents") + p("employer_nssf_cents"), "NSSF, both shares"),
            ("2330", 0, p("shif_cents"), "SHIF withheld"),
            ("2340", 0, p("levy_cents") + p("employer_levy_cents"), "Housing Levy, both shares"),
            ("1210", 0, p("advance_cents"), "Salary advances taken back"),
        ]
    else:
        legs = [("6000", amount_cents, 0, "Salary expense"), ("1010", 0, amount_cents, "Cash paid out")]
    legs = [leg for leg in legs if leg[1] or leg[2]]
    if sum(leg[1] for leg in legs) != sum(leg[2] for leg in legs):
        raise ValueError(f"payroll run {payroll_run_id}: the payslips don't add up; nothing booked")

    now = datetime.now(UTC)
    entry = JournalEntry(
        org_id=org_id,
        number=_new_entry_number(now),
        entry_date=local_date(now, await business_tz(str(org_id))),
        memo=f"Payroll run {payroll_run_id} paid",
        source="payroll",
        source_ref=payroll_run_id,
        status="posted",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()

    for code, debit, credit, description in legs:
        account = await get_account_by_code(session, org_id, code)
        session.add(
            JournalLine(
                org_id=org_id,
                journal_entry_id=entry.id,
                account_id=account.id,
                debit_cents=debit,
                credit_cents=credit,
                description=description,
            )
        )
    await session.commit()
