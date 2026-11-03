import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


ACCOUNT_TYPES = ("asset", "liability", "equity", "income", "expense")
JOURNAL_SOURCES = ("manual", "invoicing", "pos", "payroll")
JOURNAL_STATUSES = ("draft", "posted")
FISCAL_PERIOD_STATUSES = ("open", "closed")
BANK_TRANSACTION_STATUSES = ("unmatched", "matched")


class Account(Base):
    """The Chart of Accounts. Self-referencing parent_id for a tree, but
    the generic list/kanban/form renderer has no tree view -- v1 ships as
    a flat list sorted by code (see list_accounts in main.py); a real
    expandable tree is a documented stretch goal, not missing data."""

    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class JournalEntry(Base):
    """Double-entry, enforced at the one endpoint that creates these
    (POST /journal_entries, see main.py) rather than a DB trigger/CHECK --
    Friday never uses either for cross-row business rules (RLS is the
    only DB-level enforcement anywhere in this codebase). Once posted,
    lines are immutable; a posting mistake gets a new reversing entry,
    never an edit -- same philosophy as invoicing's return_pos_sale
    fixing a sale with a new mirrored transaction instead of touching the
    original."""

    __tablename__ = "journal_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    number: Mapped[str] = mapped_column(Text, nullable=False)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    memo: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Where this entry came from: typed by hand, or posted automatically
    # by a webhook subscribed to another app's event (see
    # kernel/internal/gateway/events.go and app/webhooks.py in this app).
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    source_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["JournalLine"]] = relationship(
        back_populates="journal_entry", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def total_debit_cents(self) -> int:
        return sum(l.debit_cents for l in self.lines)

    @property
    def total_credit_cents(self) -> int:
        return sum(l.credit_cents for l in self.lines)


class JournalLine(Base):
    """Not its own top-level ResourceSpec -- embedded in JournalEntryOut,
    same child-collection shape as invoicing's InvoiceLine/inventory's
    PurchaseOrderLine. Created only via the parent entry's own endpoint,
    never independently."""

    __tablename__ = "journal_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entries.id", ondelete="CASCADE"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    debit_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    credit_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    journal_entry: Mapped["JournalEntry"] = relationship(back_populates="lines")


class FiscalPeriod(Base):
    __tablename__ = "fiscal_periods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")


class BankAccount(Base):
    __tablename__ = "bank_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    external_reference: Mapped[str] = mapped_column(Text, nullable=False, default="")


class BankTransaction(Base):
    __tablename__ = "bank_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    bank_account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("bank_accounts.id", ondelete="CASCADE"), nullable=False
    )
    txn_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unmatched")
