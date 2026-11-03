import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import FieldSpec, Principal, ResourceSpec, create_app, get_current_principal, get_org_session, resource
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .accounts import ensure_default_accounts, get_account_by_code
from .models import (
    ACCOUNT_TYPES,
    BANK_TRANSACTION_STATUSES,
    FISCAL_PERIOD_STATUSES,
    JOURNAL_SOURCES,
    JOURNAL_STATUSES,
    Account,
    BankAccount,
    BankTransaction,
    FiscalPeriod,
    JournalEntry,
    JournalLine,
)
from .schemas import (
    AccountCreate,
    AccountOut,
    BankAccountCreate,
    BankAccountOut,
    BankTransactionCreate,
    BankTransactionOut,
    FiscalPeriodCreate,
    FiscalPeriodOut,
    JournalEntryCreate,
    JournalEntryOut,
    JournalEntryStatusUpdate,
)
from .webhooks import webhooks_router

resource(
    ResourceSpec(
        name="account",
        app="accounting",
        label="Account",
        label_plural="Chart of Accounts",
        views=("list", "form"),
        search_fields=("code", "name"),
        fields=(
            FieldSpec("code", "Code", "text", required=True),
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("type", "Type", "select", options=ACCOUNT_TYPES, required=True),
            FieldSpec("parent_id", "Parent", "reference", reference="accounting.account", list_visible=False),
            FieldSpec("is_active", "Active", "boolean"),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="journal_entry",
        app="accounting",
        label="Journal Entry",
        label_plural="Journal Entries",
        views=("list", "form"),
        search_fields=("number", "memo"),
        fields=(
            FieldSpec("number", "Number", "text", form_visible=False),
            FieldSpec("entry_date", "Date", "date", required=True),
            FieldSpec("memo", "Memo", "text"),
            FieldSpec("source", "Source", "select", options=JOURNAL_SOURCES, form_visible=False),
            FieldSpec("status", "Status", "select", options=JOURNAL_STATUSES, required=True),
            FieldSpec("total_debit_cents", "Debit total", "currency", form_visible=False),
            FieldSpec("total_credit_cents", "Credit total", "currency", form_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="fiscal_period",
        app="accounting",
        label="Fiscal Period",
        label_plural="Fiscal Periods",
        views=("list", "form"),
        search_fields=("name",),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("start_date", "Start", "date", required=True),
            FieldSpec("end_date", "End", "date", required=True),
            FieldSpec("status", "Status", "select", options=FISCAL_PERIOD_STATUSES, required=True),
        ),
    )
)

resource(
    ResourceSpec(
        name="bank_account",
        app="accounting",
        label="Bank Account",
        label_plural="Bank Accounts",
        views=("list", "form"),
        search_fields=("name",),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("account_id", "GL Account", "reference", reference="accounting.account", required=True),
            FieldSpec("currency", "Currency", "text"),
            FieldSpec("external_reference", "Reference", "text"),
        ),
    )
)

resource(
    ResourceSpec(
        name="bank_transaction",
        app="accounting",
        label="Bank Transaction",
        label_plural="Bank Transactions",
        views=("list",),
        search_fields=("description",),
        fields=(
            FieldSpec("bank_account_id", "Account", "reference", reference="accounting.bank_account"),
            FieldSpec("txn_date", "Date", "date", required=True),
            FieldSpec("description", "Description", "text"),
            FieldSpec("amount_cents", "Amount", "currency", required=True),
            FieldSpec("status", "Status", "select", options=BANK_TRANSACTION_STATUSES, form_visible=False),
        ),
    )
)

app = create_app("friday-accounting")


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


accounts_router = APIRouter(prefix="/accounts", tags=["accounts"])
journal_router = APIRouter(prefix="/journal_entries", tags=["journal-entries"])
fiscal_periods_router = APIRouter(prefix="/fiscal_periods", tags=["fiscal-periods"])
bank_accounts_router = APIRouter(prefix="/bank_accounts", tags=["bank-accounts"])
bank_transactions_router = APIRouter(prefix="/bank_transactions", tags=["bank-transactions"])


@accounts_router.get("", response_model=list[AccountOut])
async def list_accounts(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    await ensure_default_accounts(session, _org(principal))
    rows = await session.execute(select(Account).where(Account.org_id == _org(principal)).order_by(Account.code))
    return rows.scalars().all()


@accounts_router.post("", response_model=AccountOut, status_code=201)
async def create_account(
    body: AccountCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.type not in ACCOUNT_TYPES:
        raise HTTPException(422, f"type must be one of {ACCOUNT_TYPES}")
    account = Account(org_id=_org(principal), created_at=datetime.now(UTC), **body.model_dump())
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


async def _get_journal_entry(session: AsyncSession, principal: Principal, entry_id: uuid.UUID) -> JournalEntry:
    entry = await session.get(JournalEntry, entry_id)
    if entry is None or str(entry.org_id) != principal.org_id:
        raise HTTPException(404, "journal entry not found")
    return entry


@journal_router.get("", response_model=list[JournalEntryOut])
async def list_journal_entries(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(JournalEntry).where(JournalEntry.org_id == _org(principal)).order_by(JournalEntry.entry_date.desc())
    )
    return [JournalEntryOut.from_model(e) for e in rows.scalars().all()]


@journal_router.get("/{entry_id}", response_model=JournalEntryOut)
async def get_journal_entry(
    entry_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    entry = await _get_journal_entry(session, principal, entry_id)
    return JournalEntryOut.from_model(entry)


@journal_router.post("", response_model=JournalEntryOut, status_code=201)
async def create_journal_entry(
    body: JournalEntryCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The only way a journal entry and its lines get created -- balance
    is enforced here, not in the database, same reasoning as every other
    cross-row business rule in this codebase (see Account's doc comment
    on JournalEntry in models.py)."""
    total_debit = sum(l.debit_cents for l in body.lines)
    total_credit = sum(l.credit_cents for l in body.lines)
    if total_debit != total_credit:
        raise HTTPException(422, f"journal entry must balance: debits {total_debit} != credits {total_credit}")
    if total_debit == 0:
        raise HTTPException(422, "journal entry must have a non-zero amount")

    now = datetime.now(UTC)
    entry = JournalEntry(
        org_id=_org(principal),
        number=f"JE-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        entry_date=body.entry_date,
        memo=body.memo,
        source="manual",
        status="draft",
        created_at=now,
        updated_at=now,
    )
    session.add(entry)
    await session.flush()
    for line in body.lines:
        session.add(
            JournalLine(
                org_id=_org(principal),
                journal_entry_id=entry.id,
                account_id=line.account_id,
                debit_cents=line.debit_cents,
                credit_cents=line.credit_cents,
                description=line.description,
            )
        )
    await session.commit()
    await session.refresh(entry, attribute_names=["lines"])
    return JournalEntryOut.from_model(entry)


@journal_router.patch("/{entry_id}/status", response_model=JournalEntryOut)
async def set_journal_entry_status(
    entry_id: uuid.UUID,
    body: JournalEntryStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """draft -> posted is the only transition; once posted, lines are
    immutable (there's no line-edit endpoint at all -- a posting mistake
    gets a new reversing entry, never an edit)."""
    if body.status not in JOURNAL_STATUSES:
        raise HTTPException(422, f"status must be one of {JOURNAL_STATUSES}")
    entry = await _get_journal_entry(session, principal, entry_id)
    if entry.status == "posted" and body.status == "draft":
        raise HTTPException(400, "a posted journal entry cannot be reverted to draft")
    entry.status = body.status
    entry.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(entry, attribute_names=["lines"])
    return JournalEntryOut.from_model(entry)


@fiscal_periods_router.get("", response_model=list[FiscalPeriodOut])
async def list_fiscal_periods(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(FiscalPeriod).where(FiscalPeriod.org_id == _org(principal)).order_by(FiscalPeriod.start_date.desc())
    )
    return rows.scalars().all()


@fiscal_periods_router.post("", response_model=FiscalPeriodOut, status_code=201)
async def create_fiscal_period(
    body: FiscalPeriodCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.status not in FISCAL_PERIOD_STATUSES:
        raise HTTPException(422, f"status must be one of {FISCAL_PERIOD_STATUSES}")
    period = FiscalPeriod(org_id=_org(principal), **body.model_dump())
    session.add(period)
    await session.commit()
    await session.refresh(period)
    return period


@bank_accounts_router.get("", response_model=list[BankAccountOut])
async def list_bank_accounts(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(BankAccount).where(BankAccount.org_id == _org(principal)))
    return rows.scalars().all()


@bank_accounts_router.post("", response_model=BankAccountOut, status_code=201)
async def create_bank_account(
    body: BankAccountCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    bank_account = BankAccount(org_id=_org(principal), **body.model_dump())
    session.add(bank_account)
    await session.commit()
    await session.refresh(bank_account)
    return bank_account


@bank_transactions_router.get("", response_model=list[BankTransactionOut])
async def list_bank_transactions(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(BankTransaction)
        .where(BankTransaction.org_id == _org(principal))
        .order_by(BankTransaction.txn_date.desc())
    )
    return rows.scalars().all()


@bank_transactions_router.post("", response_model=BankTransactionOut, status_code=201)
async def create_bank_transaction(
    body: BankTransactionCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    txn = BankTransaction(org_id=_org(principal), status="unmatched", **body.model_dump())
    session.add(txn)
    await session.commit()
    await session.refresh(txn)
    return txn


@bank_transactions_router.patch("/{txn_id}/match", response_model=BankTransactionOut)
async def match_bank_transaction(
    txn_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Marks a bank transaction matched -- manual reconciliation only in
    v1 (no bank feed import), the same scope boundary as every other
    "table stakes, not the advanced version" item in this app."""
    txn = await session.get(BankTransaction, txn_id)
    if txn is None or str(txn.org_id) != principal.org_id:
        raise HTTPException(404, "bank transaction not found")
    txn.status = "matched"
    await session.commit()
    await session.refresh(txn)
    return txn


app.include_router(accounts_router)
app.include_router(journal_router)
app.include_router(fiscal_periods_router)
app.include_router(bank_accounts_router)
app.include_router(bank_transactions_router)
app.include_router(webhooks_router)
