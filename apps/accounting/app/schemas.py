import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class AccountCreate(BaseModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    type: str
    parent_id: uuid.UUID | None = None
    is_active: bool = True


class AccountOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    code: str
    name: str
    type: str
    parent_id: uuid.UUID | None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class JournalLineIn(BaseModel):
    account_id: uuid.UUID
    debit_cents: int = Field(ge=0, default=0)
    credit_cents: int = Field(ge=0, default=0)
    description: str = ""


class JournalLineOut(JournalLineIn):
    id: uuid.UUID

    model_config = {"from_attributes": True}


class JournalEntryCreate(BaseModel):
    entry_date: date
    memo: str = ""
    lines: list[JournalLineIn] = Field(min_length=2)


class JournalEntryStatusUpdate(BaseModel):
    status: str


class JournalEntryOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    number: str
    entry_date: date
    memo: str
    source: str
    source_ref: str
    status: str
    created_at: datetime
    updated_at: datetime
    lines: list[JournalLineOut]
    total_debit_cents: int
    total_credit_cents: int

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, entry) -> "JournalEntryOut":
        return cls(
            id=entry.id,
            org_id=entry.org_id,
            number=entry.number,
            entry_date=entry.entry_date,
            memo=entry.memo,
            source=entry.source,
            source_ref=entry.source_ref,
            status=entry.status,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
            lines=[JournalLineOut.model_validate(l) for l in entry.lines],
            total_debit_cents=entry.total_debit_cents,
            total_credit_cents=entry.total_credit_cents,
        )


class FiscalPeriodCreate(BaseModel):
    name: str = Field(min_length=1)
    start_date: date
    end_date: date
    status: str = "open"


class FiscalPeriodOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    start_date: date
    end_date: date
    status: str

    model_config = {"from_attributes": True}


class BankAccountCreate(BaseModel):
    name: str = Field(min_length=1)
    account_id: uuid.UUID
    currency: str = "USD"
    external_reference: str = ""


class BankAccountOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    account_id: uuid.UUID
    currency: str
    external_reference: str

    model_config = {"from_attributes": True}


class BankTransactionCreate(BaseModel):
    bank_account_id: uuid.UUID
    txn_date: date
    description: str = ""
    amount_cents: int


class BankTransactionOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    bank_account_id: uuid.UUID
    txn_date: date
    description: str
    amount_cents: int
    status: str

    model_config = {"from_attributes": True}


class LedgerLineOut(BaseModel):
    journal_entry_id: uuid.UUID
    number: str
    entry_date: date
    description: str
    debit_cents: int
    credit_cents: int
    balance_cents: int


class ReportLineOut(BaseModel):
    account_id: uuid.UUID
    code: str
    name: str
    amount_cents: int


class ProfitAndLossOut(BaseModel):
    start_date: date
    end_date: date
    income: list[ReportLineOut]
    expenses: list[ReportLineOut]
    total_income_cents: int
    total_expenses_cents: int
    net_income_cents: int


class BalanceSheetOut(BaseModel):
    as_of_date: date
    assets: list[ReportLineOut]
    liabilities: list[ReportLineOut]
    equity: list[ReportLineOut]
    net_income_to_date_cents: int
    total_assets_cents: int
    total_liabilities_cents: int
    total_equity_cents: int


class CashFlowBySourceOut(BaseModel):
    source: str
    net_cents: int


class CashFlowOut(BaseModel):
    start_date: date
    end_date: date
    beginning_balance_cents: int
    by_source: list[CashFlowBySourceOut]
    net_change_cents: int
    ending_balance_cents: int
