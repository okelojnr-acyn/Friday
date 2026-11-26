import uuid
from typing import Literal
from datetime import date, datetime

from pydantic import BaseModel, Field


class EmployeeCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str
    department: str = ""
    pay_rate_cents: int = 0
    pay_frequency: str = "monthly"
    status: str = "active"
    # For the monthly returns; checked in main._statutory_numbers.
    kra_pin: str = Field(default="", max_length=20)
    national_id: str = Field(default="", max_length=20)
    nssf_number: str = Field(default="", max_length=20)
    sha_number: str = Field(default="", max_length=20)


class EmployeeOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    user_id: str
    name: str
    email: str
    department: str
    # None when the caller doesn't handle pay (plan 12.2).
    pay_rate_cents: int | None
    pay_frequency: str
    status: str
    wallet_address: str
    wallet_network: str
    kra_pin: str = ""
    national_id: str = ""
    nssf_number: str = ""
    sha_number: str = ""
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
    # True: "I paid, pay me back"; False: "the business paid" (recorded, never paid out).
    # paid_from says which money, and wins over reimburse when sent.
    reimburse: bool = True
    paid_from: Literal["own", "petty_cash", "business"] | None = None
    # What it was for (Guss and older apps send none: daily running).
    for_kind: Literal["daily", "task", "project", "vehicle", "trip", "meeting"] = "daily"
    for_id: str = Field(default="", max_length=64)
    for_label: str = Field(default="", max_length=120)
    category: Literal["transport", "fuel", "meals", "accommodation", "airtime", "supplies", "repairs", "cleaning", "other"] = "other"
    no_receipt_reason: str = Field(default="", max_length=200)
    etims_invoice_no: str = Field(default="", max_length=40)
    # Asked first: the approved request it was spent under; or, not asked,
    # why (an emergency: always allowed, goes one level higher).
    request_id: uuid.UUID | None = None
    emergency_reason: str = Field(default="", max_length=300)
    # Petty cash: which float it came out of (the only one when there's one).
    float_id: uuid.UUID | None = None


class ExpenseClaimStatusUpdate(BaseModel):
    status: str
    # Required when rejecting: what to fix.
    note: str = Field(default="", max_length=300)


class ExpenseClaimResend(BaseModel):
    """A rejected claim, fixed and sent again (fields left out stay)."""

    description: str | None = Field(default=None, min_length=1)
    amount_cents: int | None = Field(default=None, gt=0)
    reimburse: bool | None = None
    no_receipt_reason: str | None = Field(default=None, max_length=200)
    etims_invoice_no: str | None = Field(default=None, max_length=40)


class ExpenseClaimPay(BaseModel):
    """How it was paid. crypto sends through the wallet; the others record
    a payment made outside Friday (an M-Pesa code, a bank reference)."""

    method: Literal["crypto", "mpesa", "bank", "cash"] = "crypto"
    reference: str = Field(default="", max_length=60)


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
    reimburse: bool
    receipt_sha: str = ""
    submitted_at: datetime
    waiting_on_user_id: str = ""
    waiting_on_name: str = ""
    decision_note: str = ""
    decided_by_name: str = ""
    decided_at: datetime | None = None
    paid_method: str = ""
    paid_reference: str = ""
    paid_at: datetime | None = None
    for_kind: str = "daily"
    for_id: str = ""
    for_label: str = ""
    category: str = "other"
    paid_from: str = "own"
    no_receipt_reason: str = ""
    etims_invoice_no: str = ""
    request_id: uuid.UUID | None = None
    emergency_reason: str = ""
    flag: str = ""
    float_id: uuid.UUID | None = None

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
    nssf_cents: int = 0
    shif_cents: int = 0
    levy_cents: int = 0
    paye_cents: int = 0
    net_cents: int = 0
    employer_nssf_cents: int = 0
    employer_levy_cents: int = 0
    advance_cents: int = 0
    unpaid_days: int = 0
    unpaid_cents: int = 0

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
    nssf_cents: int = 0
    shif_cents: int = 0
    levy_cents: int = 0
    paye_cents: int = 0
    net_cents: int = 0
    advance_cents: int = 0
    unpaid_days: int = 0
    unpaid_cents: int = 0


class MeetingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    starts_at: datetime
    ends_at: datetime
    # Outside guests for Google Calendar (comma-separated emails).
    attendee_emails: str = ""
    # Members of the business invited (they're told, and answer).
    attendee_user_ids: list[str] = Field(default_factory=list, max_length=100)


class MeetingUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    attendee_emails: str | None = None
    attendee_user_ids: list[str] | None = Field(default=None, max_length=100)


class MeetingResponse(BaseModel):
    response: Literal["accepted", "declined"]


class MeetingAttendeeOut(BaseModel):
    user_id: str
    name: str
    email: str
    response: str

    model_config = {"from_attributes": True}


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
    created_by_user_id: str = ""
    created_by_name: str = ""
    attendees: list[MeetingAttendeeOut] = []
    # Mine: organiser, or my answer (invited, accepted, declined); "" = neither.
    my_role: str = ""

    model_config = {"from_attributes": True}


class SalaryAdvanceCreate(BaseModel):
    amount_cents: int = Field(gt=0)
    # Paid back over this many pay runs.
    months: int = Field(default=1, ge=1, le=3)
    description: str = Field(default="", max_length=300)


class SalaryAdvanceOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    description: str
    amount_cents: int
    currency: str
    months: int
    status: str
    waiting_on_name: str = ""
    decision_note: str = ""
    decided_by_name: str = ""
    paid_method: str = ""
    paid_reference: str = ""
    recovered_cents: int = 0
    submitted_at: datetime

    model_config = {"from_attributes": True}


class TimeOffCreate(BaseModel):
    kind: Literal["annual", "sick", "unpaid"]
    starts_on: date
    ends_on: date
    note: str = Field(default="", max_length=300)


class TimeOffOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    kind: str
    starts_on: date
    ends_on: date
    days: int
    note: str
    status: str
    waiting_on_name: str = ""
    decision_note: str = ""
    decided_by_name: str = ""
    submitted_at: datetime
    # Filled where the list shows whose it is (calendars).
    employee_name: str = ""

    model_config = {"from_attributes": True}


class CoverSet(BaseModel):
    delegate_user_id: str = Field(min_length=1, max_length=64)
    starts_on: date
    ends_on: date


FOR_KINDS = Literal["daily", "task", "project", "vehicle", "trip", "meeting"]
CATEGORIES = Literal["transport", "fuel", "meals", "accommodation", "airtime", "supplies", "repairs", "cleaning", "other"]


class SpendRequestCreate(BaseModel):
    """Asking first. A trip says where and when, and may ask for cash up
    front (at most its estimate)."""

    kind: Literal["spend", "trip"] = "spend"
    description: str = Field(min_length=1, max_length=300)
    amount_cents: int = Field(gt=0)
    for_kind: FOR_KINDS = "daily"
    for_id: str = Field(default="", max_length=64)
    for_label: str = Field(default="", max_length=120)
    category: CATEGORIES = "other"
    destination: str = Field(default="", max_length=120)
    starts_on: date | None = None
    ends_on: date | None = None
    advance_cents: int = Field(default=0, ge=0)


class TripSettle(BaseModel):
    """How a trip's advance is squared: what's left comes back (cash,
    M-Pesa, bank) or off the next pay (payroll); an overspend is paid to
    the person (cash, M-Pesa, bank)."""

    method: Literal["cash", "mpesa", "bank", "payroll"] = "cash"
    reference: str = Field(default="", max_length=60)


class SpendRequestOut(BaseModel):
    id: uuid.UUID
    employee_id: uuid.UUID
    kind: str
    description: str
    amount_cents: int
    currency: str
    for_kind: str
    for_id: str
    for_label: str
    category: str
    destination: str = ""
    starts_on: date | None = None
    ends_on: date | None = None
    advance_cents: int = 0
    status: str
    waiting_on_name: str = ""
    decision_note: str = ""
    decided_by_name: str = ""
    advance_method: str = ""
    advance_reference: str = ""
    advance_paid_at: datetime | None = None
    spent_cents: int = 0
    settle_method: str = ""
    closed_at: datetime | None = None
    submitted_at: datetime

    model_config = {"from_attributes": True}


class PettyFloatCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    location_id: str = Field(default="", max_length=64)
    holder_user_id: str = Field(min_length=1, max_length=64)
    float_cents: int | None = Field(default=None, gt=0)  # None: the spending policy's


class PettyFloatUpdate(BaseModel):
    holder_user_id: str | None = Field(default=None, min_length=1, max_length=64)
    float_cents: int | None = Field(default=None, gt=0)
    active: bool | None = None


class PettyTopUp(BaseModel):
    method: Literal["cash", "mpesa", "bank"] = "cash"
    reference: str = Field(default="", max_length=60)


class PettyCount(BaseModel):
    counted_cents: int = Field(ge=0)
    note: str = Field(default="", max_length=300)


class PettyMoveOut(BaseModel):
    id: uuid.UUID
    kind: str
    amount_cents: int
    claim_id: uuid.UUID | None = None
    method: str = ""
    reference: str = ""
    note: str = ""
    by_name: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class PettyFloatOut(BaseModel):
    id: uuid.UUID
    name: str
    location_id: str
    holder_user_id: str
    holder_name: str
    float_cents: int
    currency: str
    active: bool
    # For the holder and those who pay people; None for everyone else.
    balance_cents: int | None = None
    # Slips sent or approved but not yet confirmed out of the box.
    pending_cents: int | None = None
    held_by_me: bool = False
    moves: list[PettyMoveOut] = []
