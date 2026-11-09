import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str
    department: str = ""
    pay_rate_cents: int = 0
    pay_frequency: str = "monthly"
    status: str = "active"


class EmployeeOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    user_id: str
    name: str
    email: str
    department: str
    pay_rate_cents: int
    pay_frequency: str
    status: str
    wallet_address: str
    wallet_network: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WalletLinkUpdate(BaseModel):
    wallet_address: str = Field(min_length=1)
    wallet_network: str = Field(min_length=1)


class WalletLinkOut(BaseModel):
    wallet_address: str
    wallet_network: str

    model_config = {"from_attributes": True}


class ExpenseClaimCreate(BaseModel):
    description: str = Field(min_length=1)
    amount_cents: int = Field(gt=0)
    currency: str = "USD"
    receipt_url: str = ""


class ExpenseClaimStatusUpdate(BaseModel):
    status: str


class EmployeeSaleOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    invoice_number: str
    amount_cents: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ExpenseClaimOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    employee_id: uuid.UUID
    description: str
    amount_cents: int
    currency: str
    status: str
    receipt_url: str
    submitted_at: datetime

    model_config = {"from_attributes": True}


class PayrollRunCreate(BaseModel):
    period_start: datetime
    period_end: datetime
    payout_method: str = "crypto"
    currency: str = "USD"
    employee_ids: list[uuid.UUID] = Field(min_length=1)


class PayrollLineOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    gross_amount_cents: int
    to_address: str
    network: str
    status: str
    external_id: str

    model_config = {"from_attributes": True}


class PayrollRunOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    payout_method: str
    status: str
    currency: str
    created_at: datetime
    updated_at: datetime
    lines: list[PayrollLineOut]
    total_amount_cents: int

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, run) -> "PayrollRunOut":
        return cls(
            id=run.id,
            org_id=run.org_id,
            period_start=run.period_start,
            period_end=run.period_end,
            payout_method=run.payout_method,
            status=run.status,
            currency=run.currency,
            created_at=run.created_at,
            updated_at=run.updated_at,
            lines=[PayrollLineOut.model_validate(l) for l in run.lines],
            total_amount_cents=run.total_amount_cents,
        )


class MyPayrollLineOut(BaseModel):
    """The employee-facing view of one of their own payroll lines --
    deliberately not PayrollRunOut, which nests every employee's line in
    the run and would leak coworkers' pay."""

    payroll_run_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    run_status: str
    gross_amount_cents: int
    currency: str
    line_status: str


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1)
    starts_at: datetime
    ends_at: datetime
    attendee_emails: str = ""


class MeetingUpdate(BaseModel):
    title: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    attendee_emails: str | None = None


class MeetingOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    attendee_emails: str
    created_by_email: str
    calendar_event_id: str
    calendar_link: str
    sync_status: str
    sync_error: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
