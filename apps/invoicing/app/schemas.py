import uuid
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str = ""
    company: str = ""
    payment_terms_days: int = 30


class CustomerOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    email: str
    company: str
    payment_terms_days: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomerBulkCreate(BaseModel):
    customers: list[CustomerCreate] = Field(min_length=1)


class LineIn(BaseModel):
    description: str = Field(min_length=1)
    quantity: Decimal = Decimal(1)
    unit_price_cents: int = 0
    tax_rate_bp: int = 0
    discount_bp: int = 0
    unit_cost_cents: int | None = None
    product_id: uuid.UUID | None = None


class LineOut(LineIn):
    id: uuid.UUID
    total_cents: int
    tax_cents: int

    model_config = {"from_attributes": True}


class InvoiceCreate(BaseModel):
    customer_id: uuid.UUID | None = None
    currency: str = "USD"
    lines: list[LineIn] = []
    recurring_interval: str = ""


class InvoiceStatusUpdate(BaseModel):
    status: str


class PayWithCardOut(BaseModel):
    client_secret: str | None
    publishable_key: str


class PayWithPesapalOut(BaseModel):
    invoice_id: uuid.UUID
    redirect_url: str


class PosSaleStatusOut(BaseModel):
    invoice_id: uuid.UUID
    status: str


class PaymentCreate(BaseModel):
    amount_cents: int = Field(gt=0)
    method: str = "other"


class PaymentOut(BaseModel):
    id: uuid.UUID
    amount_cents: int
    method: str
    received_at: datetime

    model_config = {"from_attributes": True}


class PosShiftOpen(BaseModel):
    opening_float_cents: int = Field(ge=0, default=0)


class PosShiftClose(BaseModel):
    closing_count_cents: int = Field(ge=0)


class PosShiftOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    opened_at: datetime
    closed_at: datetime | None
    opening_float_cents: int
    closing_count_cents: int | None
    expected_cents: int | None
    status: str
    opened_by_user_id: str | None
    opened_by_email: str | None

    model_config = {"from_attributes": True}


class InvoiceOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    customer_id: uuid.UUID | None
    number: str
    status: str
    currency: str
    source: str
    source_ref: str | None
    cashier_user_id: str | None
    cashier_email: str | None
    due_at: datetime | None
    recurring_interval: str
    next_recurrence_at: datetime | None
    created_at: datetime
    updated_at: datetime
    lines: list[LineOut]
    payments: list[PaymentOut]
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    paid_cents: int
    balance_cents: int
    kind: str = "invoice"
    valid_until: datetime | None = None
    # Computed, not stored: kind=invoice, status=sent, past due_at, balance > 0.
    is_overdue: bool = False
    days_overdue: int = 0

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, inv) -> "InvoiceOut":
        subtotal = sum(line.total_cents for line in inv.lines)
        tax = sum(line.tax_cents for line in inv.lines)
        total = subtotal + tax
        paid = sum(p.amount_cents for p in inv.payments)
        now = datetime.now(UTC)
        overdue = inv.is_overdue(now)
        return cls(
            id=inv.id,
            org_id=inv.org_id,
            customer_id=inv.customer_id,
            number=inv.number,
            kind=inv.kind,
            valid_until=inv.valid_until,
            is_overdue=overdue,
            days_overdue=(now - inv.due_at).days if overdue else 0,
            status=inv.status,
            currency=inv.currency,
            source=inv.source,
            source_ref=inv.source_ref,
            cashier_user_id=inv.cashier_user_id,
            cashier_email=inv.cashier_email,
            due_at=inv.due_at,
            recurring_interval=inv.recurring_interval,
            next_recurrence_at=inv.next_recurrence_at,
            created_at=inv.created_at,
            updated_at=inv.updated_at,
            lines=[
                LineOut(
                    id=l.id,
                    description=l.description,
                    quantity=l.quantity,
                    unit_price_cents=l.unit_price_cents,
                    tax_rate_bp=l.tax_rate_bp,
                    discount_bp=l.discount_bp,
                    unit_cost_cents=l.unit_cost_cents,
                    product_id=l.product_id,
                    total_cents=l.total_cents,
                    tax_cents=l.tax_cents,
                )
                for l in inv.lines
            ],
            payments=[PaymentOut.model_validate(p) for p in inv.payments],
            subtotal_cents=subtotal,
            tax_cents=tax,
            total_cents=total,
            paid_cents=paid,
            balance_cents=total - paid,
        )


class QuoteCreate(BaseModel):
    customer_id: uuid.UUID | None = None
    currency: str = "USD"
    lines: list[LineIn] = Field(min_length=1)
    # Days the quote stays valid; sets valid_until at creation.
    valid_days: int = Field(default=30, ge=1, le=365)
    # Optional link back to the CRM deal this quote was built for --
    # stored in source_ref so the converted invoice can carry it too.
    opportunity_id: str | None = None


class QuoteStatusUpdate(BaseModel):
    status: str


class ArAgingBucketTotals(BaseModel):
    current_cents: int = 0
    days_1_30_cents: int = 0
    days_31_60_cents: int = 0
    days_61_90_cents: int = 0
    days_over_90_cents: int = 0
    total_cents: int = 0


class ArAgingCustomerRow(ArAgingBucketTotals):
    customer_id: uuid.UUID | None
    customer_name: str
    currency: str
    invoice_count: int = 0


class ArAgingCurrencyTotals(ArAgingBucketTotals):
    currency: str


class ArAgingOut(BaseModel):
    """Open receivables (kind=invoice, status=sent, balance > 0) bucketed
    by days past due. One row per (customer, currency) and one total per
    currency -- amounts in different currencies are never summed."""

    as_of: datetime
    rows: list[ArAgingCustomerRow]
    totals: list[ArAgingCurrencyTotals]
