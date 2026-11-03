import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


INVOICE_STATUSES = ("draft", "sent", "paid", "void")
PAYMENT_METHODS = ("cash", "card", "pos", "bank_transfer", "refund", "other")
RECURRING_INTERVALS = ("", "weekly", "monthly", "yearly")
POS_SHIFT_STATUSES = ("open", "closed")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    company: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set once a "Pay with card" PaymentIntent has been created for this
    # invoice (see friday_common.integrations.stripe.StripeProvider and
    # pay_with_card below) -- lets the Stripe webhook find its way back to
    # the right invoice without trusting the webhook body alone.
    stripe_payment_intent_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # "" means this invoice isn't a recurring template. A non-empty value
    # makes generate_recurring_invoices (see main.py) clone this invoice's
    # lines into a fresh draft invoice once `next_recurrence_at` passes.
    recurring_interval: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    next_recurrence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=1)
    unit_price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Set when this line was rung up from the POS product catalog (see
    # pos_router.record_pos_sale) -- lets a later return
    # (pos_router.return_pos_sale) restock the right product. Plain
    # column, no FK -- see 0003_pos_returns.sql's comment.
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")

    @property
    def total_cents(self) -> int:
        return int(self.quantity * self.unit_price_cents)


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="other")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    invoice: Mapped["Invoice"] = relationship(back_populates="payments")


class PosShift(Base):
    """Cash-drawer reconciliation: a cashier opens a shift with a known
    starting cash float, the register keeps selling, and closing the
    shift compares the counted cash in the drawer against what cash
    sales during the window say should be there. One open shift per
    org at a time (see open_pos_shift's check) -- a second register
    needing its own concurrent shift is a real gap this doesn't cover,
    documented rather than silently wrong."""

    __tablename__ = "pos_shifts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opening_float_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Set only at close time: what the cashier actually counted, and
    # what the ledger says should be there (opening float + cash
    # payments recorded during the window). The difference between them
    # is the over/under -- computed by the caller from these two
    # fields, not stored as its own column.
    closing_count_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    expected_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
