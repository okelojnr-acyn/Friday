import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# "pending" (a POS sale submitted to a real payment gateway but not yet
# confirmed -- see pay_with_pesapal/pesapal_webhook in main.py/webhooks.py)
# is a real value the DB's CHECK constraint allows (0007_pos_identity.sql)
# but is deliberately NOT listed here: it's an internal transient state
# set only by that one code path, never something set_invoice_status
# should let a user pick from the manual dropdown.
INVOICE_STATUSES = ("draft", "sent", "paid", "void")
# A quote's own lifecycle (see 0009_quotes.sql). "accepted" is set only by
# convert_quote, never picked by hand, so it isn't in QUOTE_MANUAL_STATUSES.
QUOTE_STATUSES = ("draft", "sent", "accepted", "declined")
QUOTE_MANUAL_STATUSES = ("draft", "sent", "declined")
DOCUMENT_KINDS = ("invoice", "quote")
PAYMENT_METHODS = ("cash", "card", "pos", "bank_transfer", "refund", "pesapal", "other")
RECURRING_INTERVALS = ("", "weekly", "monthly", "yearly")
POS_SHIFT_STATUSES = ("open", "closed")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    company: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Days after an invoice is created that it's due -- see create_invoice,
    # which sets due_at from this at creation time (net-30 by default).
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    number: Mapped[str] = mapped_column(Text, nullable=False)
    # "invoice" or "quote" -- see 0009_quotes.sql for why one table.
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default="invoice")
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
    # Who rang this up -- set by record_pos_sale/return_pos_sale/
    # pay_with_pesapal from Principal.user_id/email. NULL for manual/
    # recurring invoices, which have no single "cashier". user_id is the
    # reliable match (see apps/minions's _resolve_my_employee for the
    # same user_id-then-email pattern used to resolve this back to an
    # Employee); email rides along for display even if that lookup fails.
    cashier_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    cashier_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["InvoiceLine"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", lazy="selectin"
    )

    # The one definition of "what the customer owes". Before 2026-11-10,
    # record_payment / pay_with_card / the Stripe webhook each summed
    # line.total_cents only -- the *pre-tax* subtotal -- so an invoice
    # with per-line tax was marked paid (and charged by card) without the
    # tax. POS lines carry tax_rate_bp=0 (tax arrives as its own
    # reconciling line), so this is identical to the old sum for POS.
    @property
    def grand_total_cents(self) -> int:
        return sum(line.total_cents + line.tax_cents for line in self.lines)

    @property
    def paid_cents(self) -> int:
        return sum(p.amount_cents for p in self.payments)

    @property
    def balance_cents(self) -> int:
        return self.grand_total_cents - self.paid_cents

    def is_overdue(self, now: datetime) -> bool:
        return (
            self.kind == "invoice"
            and self.status == "sent"
            and self.due_at is not None
            and self.due_at < now
            and self.balance_cents > 0
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
    # Basis points (1/100 of a percent) so a line can carry its own tax
    # rate instead of record_pos_sale's old single synthetic "Tax" line --
    # also what lets Accounting's pos-sale-cogs webhook split revenue vs.
    # tax correctly per line rather than per invoice.
    tax_rate_bp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Basis points, mirroring pos-engine/src/cart.rs's LineItem.discount_bp
    # exactly -- set by record_pos_sale from the register's real per-line
    # discount (see that function's own doc comment for why total_cents
    # has to apply this rather than trusting the client's gross total).
    discount_bp: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The product's cost basis at sale time, when known (rung up from the
    # catalog) -- None for freeform/manual lines. Lets Accounting's future
    # COGS webhook post Dr COGS / Cr Inventory Asset without ever querying
    # Inventory directly (apps only talk through the kernel event bus).
    unit_cost_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Set when this line was rung up from the POS product catalog (see
    # pos_router.record_pos_sale) -- lets a later return
    # (pos_router.return_pos_sale) restock the right product. Plain
    # column, no FK -- see 0003_pos_returns.sql's comment.
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    invoice: Mapped["Invoice"] = relationship(back_populates="lines")

    @property
    def total_cents(self) -> int:
        return int(self.quantity * self.unit_price_cents * (10_000 - self.discount_bp) / 10_000)

    @property
    def tax_cents(self) -> int:
        return self.total_cents * self.tax_rate_bp // 10000


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
    # Who opened the drawer -- set by open_pos_shift from
    # Principal.user_id/email. Accountability for this specific shift's
    # cash float; individual sales carry their own cashier identity on
    # Invoice (see cashier_user_id above) independently of who opened
    # the shift they happened during.
    opened_by_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_by_email: Mapped[str | None] = mapped_column(Text, nullable=True)
