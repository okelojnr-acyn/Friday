"""Hand-written report screens -- aggregation reads over the ledger, not
CRUD, so these don't go through the generic ResourceSpec renderer (same
justification as the POS register, Invoicing's Pay-with-card, Inventory's
Create-PO, and Web3's Treasury -- see ARCHITECTURE.md).

Only posted entries ever count toward a report -- a draft manual entry
(the only kind that can still be draft; every webhook-posted entry is
"posted" immediately, see webhooks.py) hasn't happened yet as far as the
books are concerned.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from friday_common import Principal, get_current_principal, get_org_session
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .accounts import ensure_default_accounts, get_account_by_code
from .models import Account, JournalEntry, JournalLine
from .schemas import (
    BalanceSheetOut,
    CashFlowBySourceOut,
    CashFlowOut,
    LedgerLineOut,
    ProfitAndLossOut,
    ReportLineOut,
)

reports_router = APIRouter(prefix="/reports", tags=["reports"])
ledger_router = APIRouter(prefix="/accounts", tags=["ledger"])


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


async def _account_amounts(
    session: AsyncSession,
    org_id: uuid.UUID,
    types: tuple[str, ...],
    start_date: date | None,
    end_date: date | None,
) -> list[tuple[uuid.UUID, str, str, str, int, int]]:
    """(account_id, code, name, type, total_debit_cents, total_credit_cents)
    for every account of the given type(s) with at least one posted line
    in range -- the shared aggregation every report below slices
    differently."""
    conditions = [
        JournalLine.org_id == org_id,
        JournalLine.account_id == Account.id,
        JournalLine.journal_entry_id == JournalEntry.id,
        JournalEntry.status == "posted",
        Account.type.in_(types),
    ]
    if start_date is not None:
        conditions.append(JournalEntry.entry_date >= start_date)
    if end_date is not None:
        conditions.append(JournalEntry.entry_date <= end_date)

    rows = await session.execute(
        select(
            Account.id,
            Account.code,
            Account.name,
            Account.type,
            func.coalesce(func.sum(JournalLine.debit_cents), 0),
            func.coalesce(func.sum(JournalLine.credit_cents), 0),
        )
        .where(*conditions)
        .group_by(Account.id, Account.code, Account.name, Account.type)
        .order_by(Account.code)
    )
    return rows.all()


@reports_router.get("/profit-and-loss", response_model=ProfitAndLossOut)
async def profit_and_loss(
    start_date: date = Query(...),
    end_date: date = Query(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    org_id = _org(principal)
    await ensure_default_accounts(session, org_id)
    rows = await _account_amounts(session, org_id, ("income", "expense"), start_date, end_date)

    income: list[ReportLineOut] = []
    expenses: list[ReportLineOut] = []
    for account_id, code, name, type_, debit, credit in rows:
        # income has a normal credit balance, expense a normal debit
        # balance -- each amount below is reported positive in its own
        # section.
        amount = (credit - debit) if type_ == "income" else (debit - credit)
        if amount == 0:
            continue
        line = ReportLineOut(account_id=account_id, code=code, name=name, amount_cents=amount)
        (income if type_ == "income" else expenses).append(line)

    total_income = sum(l.amount_cents for l in income)
    total_expenses = sum(l.amount_cents for l in expenses)
    return ProfitAndLossOut(
        start_date=start_date,
        end_date=end_date,
        income=income,
        expenses=expenses,
        total_income_cents=total_income,
        total_expenses_cents=total_expenses,
        net_income_cents=total_income - total_expenses,
    )


@reports_router.get("/balance-sheet", response_model=BalanceSheetOut)
async def balance_sheet(
    as_of_date: date = Query(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Cash-basis, no closing entries ever zero out income/expense
    accounts -- so net income since inception is folded into Equity here
    the same way a real close would, keeping Assets == Liabilities +
    Equity by construction (every journal entry already balances)."""
    org_id = _org(principal)
    await ensure_default_accounts(session, org_id)

    rows = await _account_amounts(session, org_id, ("asset", "liability", "equity"), None, as_of_date)
    assets: list[ReportLineOut] = []
    liabilities: list[ReportLineOut] = []
    equity: list[ReportLineOut] = []
    buckets = {"asset": assets, "liability": liabilities, "equity": equity}
    for account_id, code, name, type_, debit, credit in rows:
        amount = (debit - credit) if type_ == "asset" else (credit - debit)
        if amount == 0:
            continue
        buckets[type_].append(ReportLineOut(account_id=account_id, code=code, name=name, amount_cents=amount))

    # income (normal credit balance) and expense (normal debit balance)
    # both net the same way here: credit - debit is positive income,
    # negative when expenses exceed it.
    income_expense_rows = await _account_amounts(session, org_id, ("income", "expense"), None, as_of_date)
    net_income = sum(credit - debit for _, _, _, _, debit, credit in income_expense_rows)

    total_assets = sum(l.amount_cents for l in assets)
    total_liabilities = sum(l.amount_cents for l in liabilities)
    total_equity = sum(l.amount_cents for l in equity) + net_income
    return BalanceSheetOut(
        as_of_date=as_of_date,
        assets=assets,
        liabilities=liabilities,
        equity=equity,
        net_income_to_date_cents=net_income,
        total_assets_cents=total_assets,
        total_liabilities_cents=total_liabilities,
        total_equity_cents=total_equity,
    )


@reports_router.get("/cash-flow", response_model=CashFlowOut)
async def cash_flow(
    start_date: date = Query(...),
    end_date: date = Query(...),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Direct method, grouped by the source that moved the cash (manual /
    invoicing / pos / payroll) -- a real indirect-method statement with
    operating/investing/financing categorization is a documented stretch
    goal, same tier as the Chart of Accounts tree view."""
    org_id = _org(principal)
    await ensure_default_accounts(session, org_id)
    cash = await get_account_by_code(session, org_id, "1010")

    beginning = await session.execute(
        select(func.coalesce(func.sum(JournalLine.debit_cents - JournalLine.credit_cents), 0))
        .where(
            JournalLine.org_id == org_id,
            JournalLine.account_id == cash.id,
            JournalLine.journal_entry_id == JournalEntry.id,
            JournalEntry.status == "posted",
            JournalEntry.entry_date < start_date,
        )
    )
    beginning_balance = beginning.scalar() or 0

    by_source_rows = await session.execute(
        select(JournalEntry.source, func.coalesce(func.sum(JournalLine.debit_cents - JournalLine.credit_cents), 0))
        .where(
            JournalLine.org_id == org_id,
            JournalLine.account_id == cash.id,
            JournalLine.journal_entry_id == JournalEntry.id,
            JournalEntry.status == "posted",
            JournalEntry.entry_date >= start_date,
            JournalEntry.entry_date <= end_date,
        )
        .group_by(JournalEntry.source)
        .order_by(JournalEntry.source)
    )
    by_source = [
        CashFlowBySourceOut(source=source, net_cents=net) for source, net in by_source_rows.all() if net != 0
    ]
    net_change = sum(l.net_cents for l in by_source)
    return CashFlowOut(
        start_date=start_date,
        end_date=end_date,
        beginning_balance_cents=beginning_balance,
        by_source=by_source,
        net_change_cents=net_change,
        ending_balance_cents=beginning_balance + net_change,
    )


@ledger_router.get("/{account_id}/ledger", response_model=list[LedgerLineOut])
async def account_ledger(
    account_id: uuid.UUID,
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Every posted line against one account, oldest first, with a
    running balance. If start_date is given the balance runs from zero at
    that point rather than carrying a true opening balance -- a documented
    gap for v1; the full (no date filter) ledger is the primary view and
    isn't affected."""
    org_id = _org(principal)
    account = await session.get(Account, account_id)
    if account is None or str(account.org_id) != str(org_id):
        raise HTTPException(404, "account not found")

    conditions = [
        JournalLine.org_id == org_id,
        JournalLine.account_id == account_id,
        JournalLine.journal_entry_id == JournalEntry.id,
        JournalEntry.status == "posted",
    ]
    if start_date is not None:
        conditions.append(JournalEntry.entry_date >= start_date)
    if end_date is not None:
        conditions.append(JournalEntry.entry_date <= end_date)

    rows = await session.execute(
        select(
            JournalEntry.id,
            JournalEntry.number,
            JournalEntry.entry_date,
            JournalLine.description,
            JournalLine.debit_cents,
            JournalLine.credit_cents,
        )
        .where(*conditions)
        .order_by(JournalEntry.entry_date, JournalEntry.created_at)
    )
    debit_normal = account.type in ("asset", "expense")
    balance = 0
    lines: list[LedgerLineOut] = []
    for entry_id, number, entry_date, description, debit, credit in rows.all():
        balance += (debit - credit) if debit_normal else (credit - debit)
        lines.append(
            LedgerLineOut(
                journal_entry_id=entry_id,
                number=number,
                entry_date=entry_date,
                description=description,
                debit_cents=debit,
                credit_cents=credit,
                balance_cents=balance,
            )
        )
    return lines
