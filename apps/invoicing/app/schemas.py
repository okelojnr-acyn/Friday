import uuid
from datetime import datetime
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


class PaymentCreate(BaseModel):
    amount_cents: int = Field(gt=0)
    method: str = "other"


class PaymentOut(BaseModel):
    id: uuid.UUID
    amount_cents: int
    method: str
    received_at: datetime

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

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, inv) -> "InvoiceOut":
        subtotal = sum(line.total_cents for line in inv.lines)
        tax = sum(line.tax_cents for line in inv.lines)
        total = subtotal + tax
        paid = sum(p.amount_cents for p in inv.payments)
        return cls(
            id=inv.id,
            org_id=inv.org_id,
            customer_id=inv.customer_id,
            number=inv.number,
            status=inv.status,
            currency=inv.currency,
            source=inv.source,
            source_ref=inv.source_ref,
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
