import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


EMPLOYEE_STATUSES = ("active", "inactive")
PAY_FREQUENCIES = ("weekly", "biweekly", "monthly")
EXPENSE_CLAIM_STATUSES = ("submitted", "approved", "rejected", "paid")
PAYROLL_RUN_STATUSES = ("draft", "approved", "paying", "paid")
PAYOUT_METHODS = ("crypto", "fiat")
PAYROLL_LINE_STATUSES = ("pending", "blocked", "sent", "confirmed", "failed")


class Employee(Base):
    """One row per member who's set up as an employee for payroll/expense
    purposes -- not every org member needs one (an owner who never draws
    a salary through Friday has no reason to appear here). wallet_address/
    wallet_network are self-set by the employee via GET/PUT /me/wallet,
    never admin-entered -- see main.py's doc comment on that endpoint for
    why (Acyn Wallet's Partner API has no email/phone lookup; payouts go
    to a raw address the employee has to supply themselves)."""

    __tablename__ = "employees"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # core.users.id -- by-id-only, no FK across schemas (see
    # ARCHITECTURE.md's "Data ownership"). The kernel has no org-member
    # directory endpoint for an admin to pick a user_id from, so this
    # starts empty at creation (admin only knows the person's email) and
    # gets backfilled the first time that person touches a self-service
    # endpoint (/me/wallet, expense claims) -- see main.py's
    # _resolve_my_employee for the claim-by-email logic.
    user_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    department: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pay_rate_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pay_frequency: Mapped[str] = mapped_column(String(16), nullable=False, default="monthly")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    wallet_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    wallet_network: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExpenseClaim(Base):
    __tablename__ = "expense_claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="submitted")
    receipt_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PayrollRun(Base):
    __tablename__ = "payroll_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payout_method: Mapped[str] = mapped_column(String(16), nullable=False, default="crypto")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["PayrollLine"]] = relationship(
        back_populates="payroll_run", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def total_amount_cents(self) -> int:
        return sum(l.gross_amount_cents for l in self.lines)


class PayrollLine(Base):
    """to_address/network are snapshotted from the employee's wallet at
    run-creation time, not live-referenced -- same reasoning Invoicing
    snapshots a price onto InvoiceLine rather than re-reading a Customer
    field that might change later. An employee changing their wallet
    address after a run is created shouldn't retroactively redirect an
    already-queued payout."""

    __tablename__ = "payroll_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payroll_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payroll_runs.id", ondelete="CASCADE"), nullable=False
    )
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="RESTRICT"), nullable=False
    )
    employee_name: Mapped[str] = mapped_column(Text, nullable=False)
    gross_amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    to_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    network: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    external_id: Mapped[str] = mapped_column(Text, nullable=False, default="")

    payroll_run: Mapped["PayrollRun"] = relationship(back_populates="lines")


class EmployeeSale(Base):
    """One row per POS sale attributed to an employee -- populated by the
    /internal/webhooks/pos-sale subscriber (see main.py), never written
    directly. employee_name is snapshotted at write time, same reasoning
    as PayrollLine.employee_name: this is a historical record, not a live
    view, so a later name change on Employee shouldn't rewrite it."""

    __tablename__ = "employee_sales"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("employees.id", ondelete="CASCADE"), nullable=False
    )
    employee_name: Mapped[str] = mapped_column(Text, nullable=False)
    invoice_number: Mapped[str] = mapped_column(Text, nullable=False)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
