"""Chart-of-accounts helpers shared by main.py (the resource-CRUD routes)
and webhooks.py (the auto-posting webhooks) -- standalone so neither
needs to import the other.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Account

# code -> (name, type) for the standard starter Chart of Accounts every
# org gets. Lazily seeded (see ensure_default_accounts) rather than
# inserted at migration time, since no org exists yet when migrations
# run.
DEFAULT_ACCOUNTS = (
    ("1010", "Cash", "asset"),
    # Money that never sits in the drawer (2026-11-16): M-Pesa and
    # Pesapal in one, card and bank in another, so the cash count and the
    # cash account agree.
    ("1020", "M-Pesa", "asset"),
    ("1030", "Card and bank", "asset"),
    ("1200", "Accounts Receivable", "asset"),
    ("1400", "Inventory Asset", "asset"),
    # VAT paid on purchases, claimed back on the VAT return.
    ("1500", "VAT Input (claimable)", "asset"),
    ("2000", "Accounts Payable", "liability"),
    # Money staff paid from their own pocket until it's paid back (Guss
    # books pay-me-back expenses here; a claim's payout clears it).
    ("2150", "Owed to staff", "liability"),
    # VAT charged on sales, owed to KRA (named "Tax Payable" before).
    ("2200", "VAT Output (payable)", "liability"),
    ("3000", "Owner's Equity", "equity"),
    ("4000", "Sales Revenue", "income"),
    ("5000", "Cost of Goods Sold", "expense"),
    # Stock written off or found missing at a count (plan 20.2 #1).
    ("5100", "Stock losses", "expense"),
    ("6000", "Salary Expense", "expense"),
    ("6900", "Shop expenses", "expense"),
)


async def ensure_default_accounts(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Idempotent upsert-by-code -- safe to call on every request that
    needs an account to exist (every webhook handler, and the first
    GET /accounts) rather than needing a dedicated "on org install" hook,
    which the kernel doesn't have."""
    existing = await session.execute(select(Account.code).where(Account.org_id == org_id))
    have = set(existing.scalars().all())
    missing = [a for a in DEFAULT_ACCOUNTS if a[0] not in have]
    if not missing:
        return
    # ON CONFLICT, not a check-then-insert: the accounts list and the P&L
    # report load concurrently on first visit, both saw "no accounts", and
    # the loser 500'd on idx_accounts_org_code (seen live 2026-11-10).
    now = datetime.now(UTC)
    await session.execute(
        pg_insert(Account)
        .values(
            [
                {"id": uuid.uuid4(), "org_id": org_id, "code": code, "name": name, "type": type_, "created_at": now}
                for code, name, type_ in missing
            ]
        )
        .on_conflict_do_nothing(index_elements=["org_id", "code"])
    )
    await session.commit()


async def get_account_by_code(session: AsyncSession, org_id: uuid.UUID, code: str) -> Account:
    rows = await session.execute(select(Account).where(Account.org_id == org_id, Account.code == code))
    account = rows.scalars().first()
    if account is None:
        raise HTTPException(500, f"default account {code!r} missing -- ensure_default_accounts should have seeded it")
    return account
