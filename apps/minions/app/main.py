import csv
import hashlib
import io
import re
import uuid
from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from friday_common import (
    first_delivery,
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_integration_config,
    get_org_session,
    get_session,
    publish_event,
    require_kernel_token,
    require_role,
    resource,
    set_org_context,
)
from friday_common.clock import business_tz, local_date, month_bounds
from friday_common.payroll_ke import band_tax_cents, kenya_deductions, nssf_tiers
from friday_common.access import (
    Scope,
    approvers_for,
    people_in,
    person_in_business,
    require,
    scope_for,
    spending_policy,
    who_can,
)
from friday_common.integrations import AcynWalletProvider, GoogleCalendarProvider
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    EMPLOYEE_STATUSES,
    ADVANCE_STATUSES,
    TIME_OFF_KINDS,
    TIME_OFF_STATUSES,
    EXPENSE_CLAIM_STATUSES,
    MEETING_SYNC_STATUSES,
    PAY_FREQUENCIES,
    PAYOUT_METHODS,
    PAYROLL_RUN_STATUSES,
    ClaimReceipt,
    Employee,
    EmployeeSale,
    ExpenseClaim,
    Meeting,
    ApprovalCover,
    MeetingAttendee,
    PettyFloat,
    PettyMove,
    SalaryAdvance,
    SpendRequest,
    TimeOff,
    PayrollLine,
    PayrollRun,
)
from .schemas import (
    EmployeeCreate,
    EmployeeOut,
    EmployeeSaleOut,
    CoverSet,
    ExpenseClaimCreate,
    ExpenseClaimOut,
    ExpenseClaimPay,
    ExpenseClaimResend,
    ExpenseClaimStatusUpdate,
    MeetingAttendeeOut,
    MeetingCreate,
    MeetingOut,
    MeetingResponse,
    MeetingUpdate,
    MyPayrollLineOut,
    SalaryAdvanceCreate,
    PettyCount,
    PettyFloatCreate,
    PettyFloatOut,
    PettyFloatUpdate,
    PettyMoveOut,
    PettyTopUp,
    SalaryAdvanceOut,
    SpendRequestCreate,
    SpendRequestOut,
    TripSettle,
    TimeOffCreate,
    TimeOffOut,
    PayrollRunCreate,
    PayrollRunOut,
    WalletLinkOut,
    WalletLinkUpdate,
)

resource(
    ResourceSpec(
        name="employee",
        app="minions",
        label="Employee",
        label_plural="Employees",
        views=("list", "form"),
        search_fields=("name", "email"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("email", "Email", "email", required=True),
            FieldSpec("department", "Department", "text"),
            FieldSpec("pay_rate_cents", "Pay rate", "currency"),
            FieldSpec("pay_frequency", "Frequency", "select", options=PAY_FREQUENCIES, required=True),
            FieldSpec("status", "Status", "select", options=EMPLOYEE_STATUSES, required=True),
            FieldSpec("kra_pin", "KRA PIN", "text", list_visible=False),
            FieldSpec("national_id", "ID number", "text", list_visible=False),
            FieldSpec("nssf_number", "NSSF number", "text", list_visible=False),
            FieldSpec("sha_number", "SHA number", "text", list_visible=False),
            FieldSpec("wallet_address", "Wallet address", "text", list_visible=False, form_visible=False),
            FieldSpec("wallet_network", "Wallet network", "text", list_visible=False, form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="expense_claim",
        app="minions",
        label="Expense Claim",
        label_plural="Expense Claims",
        views=("list", "kanban", "form"),
        kanban_group_by="status",
        search_fields=("description",),
        fields=(
            FieldSpec("employee_id", "Employee", "reference", reference="minions.employee", form_visible=False),
            FieldSpec("description", "Description", "text", required=True),
            FieldSpec("amount_cents", "Amount", "currency", required=True),
            FieldSpec("currency", "Currency", "text"),
            FieldSpec("status", "Status", "select", options=EXPENSE_CLAIM_STATUSES, required=True),
            FieldSpec("receipt_url", "Receipt", "text", list_visible=False),
            FieldSpec("submitted_at", "Submitted", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="salary_advance",
        app="minions",
        label="Salary Advance",
        label_plural="Salary Advances",
        views=("list", "form"),
        search_fields=("description",),
        fields=(
            FieldSpec("employee_id", "Employee", "reference", reference="minions.employee", form_visible=False),
            FieldSpec("amount_cents", "Amount", "currency", form_visible=False),
            FieldSpec("currency", "Currency", "text", form_visible=False),
            FieldSpec("months", "Paid back over (pay runs)", "number", form_visible=False),
            FieldSpec("status", "Status", "select", options=ADVANCE_STATUSES, form_visible=False),
            FieldSpec("description", "What for", "text", form_visible=False),
            FieldSpec("recovered_cents", "Paid back so far", "currency", form_visible=False),
            FieldSpec("submitted_at", "Asked", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="time_off",
        app="minions",
        label="Time off",
        label_plural="Time off",
        views=("list", "form"),
        search_fields=("description",),
        fields=(
            FieldSpec("employee_id", "Employee", "reference", reference="minions.employee", form_visible=False),
            FieldSpec("kind", "Kind", "select", options=TIME_OFF_KINDS, form_visible=False),
            FieldSpec("starts_on", "From", "date", form_visible=False),
            FieldSpec("ends_on", "To", "date", form_visible=False),
            FieldSpec("days", "Working days", "number", form_visible=False),
            FieldSpec("status", "Status", "select", options=TIME_OFF_STATUSES, form_visible=False),
            FieldSpec("note", "Note", "text", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="payroll_run",
        app="minions",
        label="Payroll Run",
        label_plural="Payroll Runs",
        views=("list", "form"),
        search_fields=(),
        fields=(
            FieldSpec("period_start", "Period start", "date", required=True),
            FieldSpec("period_end", "Period end", "date", required=True),
            FieldSpec("payout_method", "Payout method", "select", options=PAYOUT_METHODS, required=True),
            FieldSpec("status", "Status", "select", options=PAYROLL_RUN_STATUSES, required=True),
            FieldSpec("total_amount_cents", "Total", "currency", form_visible=False),
            FieldSpec("currency", "Currency", "text"),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="employee_sale",
        app="minions",
        label="Employee Sale",
        label_plural="Employee Sales",
        views=("list",),
        search_fields=("employee_name", "invoice_number"),
        fields=(
            FieldSpec("employee_id", "Employee", "reference", reference="minions.employee", form_visible=False),
            FieldSpec("employee_name", "Employee name", "text", form_visible=False),
            FieldSpec("invoice_number", "Sale", "text", form_visible=False),
            FieldSpec("amount_cents", "Amount", "currency", form_visible=False),
            FieldSpec("created_at", "When", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="meeting",
        app="minions",
        label="Meeting",
        label_plural="Meetings",
        views=("list", "form"),
        search_fields=("title",),
        fields=(
            FieldSpec("title", "Title", "text", required=True),
            FieldSpec("starts_at", "Starts", "datetime", required=True),
            FieldSpec("ends_at", "Ends", "datetime", required=True),
            FieldSpec("attendee_emails", "Attendees (comma-separated)", "text"),
            FieldSpec("created_by_email", "Scheduled by", "email", form_visible=False),
            FieldSpec("sync_status", "Calendar sync", "select", options=MEETING_SYNC_STATUSES, form_visible=False),
            FieldSpec("sync_error", "Sync error", "text", form_visible=False, list_visible=False),
            FieldSpec("calendar_link", "Calendar link", "text", form_visible=False, list_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

app = create_app("friday-minions")


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


async def _resolve_my_employee(session: AsyncSession, principal: Principal) -> Employee:
    """Resolves the caller's own Employee row -- by user_id if they've
    used a self-service endpoint before, otherwise by email (the only
    identifier an admin had to provision them with -- see Employee's
    own doc comment in models.py for why), claiming it by backfilling
    user_id on first match. 404s if nobody's provisioned this person as
    an employee yet, rather than silently creating one -- that's an
    admin action (POST /employees)."""
    rows = await session.execute(
        select(Employee).where(Employee.org_id == _org(principal), Employee.user_id == principal.user_id)
    )
    employee = rows.scalars().first()
    if employee is not None:
        return employee

    rows = await session.execute(
        select(Employee).where(Employee.org_id == _org(principal), Employee.email == principal.email)
    )
    employee = rows.scalars().first()
    if employee is None:
        raise HTTPException(404, "you're not set up as an employee yet -- ask an admin to add you")
    employee.user_id = principal.user_id
    await session.commit()
    await session.refresh(employee)
    return employee


async def _resolve_employee_by_identity(
    session: AsyncSession, org_id: uuid.UUID, user_id: str | None, email: str | None
) -> Employee | None:
    """Same two-step lookup as _resolve_my_employee (user_id, falling back
    to email, claiming by backfilling user_id on an email match) --
    but for resolving someone else's identity from an event payload
    (invoicing.pos_sale.recorded's cashier_user_id/cashier_email) rather
    than the current caller's own Principal. Returns None instead of
    404ing: not every cashier is a provisioned employee (an owner ringing
    up a one-off sale, say), and a webhook has no one to report an error
    to anyway."""
    if user_id:
        rows = await session.execute(select(Employee).where(Employee.org_id == org_id, Employee.user_id == user_id))
        employee = rows.scalars().first()
        if employee is not None:
            return employee

    if not email:
        return None
    rows = await session.execute(select(Employee).where(Employee.org_id == org_id, Employee.email == email))
    employee = rows.scalars().first()
    if employee is not None and user_id and not employee.user_id:
        employee.user_id = user_id
    return employee


async def _provider(principal: Principal) -> AcynWalletProvider:
    config = await get_integration_config(principal.org_id, "acyn_wallet")
    if not config.get("api_key"):
        raise HTTPException(400, "Acyn Wallet is not connected -- add an API key in Settings > Integrations")
    return AcynWalletProvider(config)


async def _calendar_provider(org_id: str) -> GoogleCalendarProvider | None:
    """None, not an exception -- Calendar sync is optional (see
    Meeting's own doc comment), so a missing/incomplete config just
    means "stays pending", the same way Employee.wallet_address being
    unset means a payroll line stays 'blocked' rather than erroring the
    whole run."""
    config = await get_integration_config(org_id, "google_calendar")
    if not (config.get("client_id") and config.get("client_secret") and config.get("refresh_token")):
        return None
    return GoogleCalendarProvider(config)


def _attendee_list(attendee_emails: str) -> list[str]:
    return [e.strip() for e in attendee_emails.split(",") if e.strip()]


async def _sync_meeting_to_calendar(meeting: Meeting) -> None:
    """Best-effort: create (or update, if already synced once) the
    Google Calendar event for meeting, mutating its sync_status/
    calendar_event_id/calendar_link/sync_error fields in place. Never
    raises -- a Calendar outage or a disconnected integration shouldn't
    turn into a 500 on what is, from the caller's point of view, a
    successful meeting create/update; the result is just visible on the
    record instead (same posture as ExpenseClaim's payout step)."""
    provider = await _calendar_provider(str(meeting.org_id))
    if provider is None:
        meeting.sync_status = "pending"
        meeting.sync_error = "Google Calendar is not connected -- add it in Settings > Integrations"
        return
    try:
        attendees = _attendee_list(meeting.attendee_emails)
        if meeting.calendar_event_id:
            event = await provider.update_event(
                meeting.calendar_event_id, meeting.title, meeting.starts_at.isoformat(), meeting.ends_at.isoformat(), attendees
            )
        else:
            event = await provider.create_event(
                meeting.title, meeting.starts_at.isoformat(), meeting.ends_at.isoformat(), attendees
            )
        meeting.calendar_event_id = event.get("id", meeting.calendar_event_id)
        meeting.calendar_link = event.get("htmlLink", meeting.calendar_link)
        meeting.sync_status = "synced"
        meeting.sync_error = ""
    except Exception as exc:  # noqa: BLE001 -- any failure here just means "stays unsynced", see doc comment
        meeting.sync_status = "error"
        meeting.sync_error = str(exc)[:500]


employees_router = APIRouter(prefix="/employees", tags=["employees"])
me_router = APIRouter(prefix="/me", tags=["me"])
expense_claims_router = APIRouter(prefix="/expense_claims", tags=["expense-claims"])
payroll_router = APIRouter(prefix="/payroll_runs", tags=["payroll"])
employee_sales_router = APIRouter(prefix="/employee_sales", tags=["employee-sales"])
meetings_router = APIRouter(prefix="/meetings", tags=["meetings"])
webhooks_router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])


@employee_sales_router.get("", response_model=list[EmployeeSaleOut])
async def list_employee_sales(
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("sales.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """Sales by person: your own, your team's, your locations' or all."""
    q = select(EmployeeSale).where(EmployeeSale.org_id == _org(principal))
    ids = await _visible_employee_ids(session, principal, scope)
    if ids is not None:
        q = q.where(EmployeeSale.employee_id.in_(ids))
    rows = await session.execute(q.order_by(EmployeeSale.created_at.desc()))
    return rows.scalars().all()


# Meetings (HR plan 8.4.3): you see the meetings you organise or are
# invited to (owners and admins: all); the organiser (or an owner or admin)
# changes or cancels one; invited members are told and answer.


def _sees_all(principal: Principal) -> bool:
    return principal.role in ("owner", "admin")


def _organises(principal: Principal, m: Meeting) -> bool:
    return m.created_by_user_id == principal.user_id or (not m.created_by_user_id and m.created_by_email == principal.email)


async def _attendees(session: AsyncSession, meeting_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[MeetingAttendee]]:
    out: dict[uuid.UUID, list[MeetingAttendee]] = {}
    if meeting_ids:
        rows = await session.execute(select(MeetingAttendee).where(MeetingAttendee.meeting_id.in_(meeting_ids)))
        for a in rows.scalars().all():
            out.setdefault(a.meeting_id, []).append(a)
    return out


def _out(principal: Principal, m: Meeting, people: list[MeetingAttendee]) -> MeetingOut:
    mine = next((a.response for a in people if a.user_id == principal.user_id), "")
    return MeetingOut.model_validate(m).model_copy(
        update={
            "attendees": [MeetingAttendeeOut.model_validate(a) for a in people],
            "my_role": "organiser" if _organises(principal, m) else mine,
        }
    )


async def _invite(session: AsyncSession, principal: Principal, m: Meeting, user_ids: list[str]) -> list[str]:
    """Sets the invited members to `user_ids` (each checked to be in the
    business); returns the newly invited ones. Their emails join the
    Google Calendar invite."""
    want = [u for u in dict.fromkeys(u.strip() for u in user_ids) if u and u != m.created_by_user_id]
    current = {a.user_id: a for a in (await _attendees(session, [m.id])).get(m.id, [])}
    for uid, a in current.items():
        if uid not in want:
            await session.delete(a)
    added, emails = [], _attendee_list(m.attendee_emails)
    for uid in want:
        if uid in current:
            continue
        person = await person_in_business(principal.org_id, user_id=uid)
        if person is None:
            raise HTTPException(422, "someone invited isn't in this business")
        session.add(MeetingAttendee(meeting_id=m.id, org_id=m.org_id, user_id=uid, name=person.get("name") or person["email"], email=person["email"]))
        added.append(uid)
        if person["email"] and person["email"] not in emails:
            emails.append(person["email"])
    m.attendee_emails = ", ".join(emails)
    return added


# How long before a meeting its people are reminded.
REMIND_BEFORE = timedelta(minutes=30)


async def _schedule_reminder(org_id: str, m: Meeting, session: AsyncSession) -> None:
    """Asks the kernel to deliver minions.meeting.reminder 30 minutes before
    the meeting (nothing polls). A reminder left behind by a move or a
    cancellation does nothing when it arrives: it carries the start time."""
    starts = m.starts_at if m.starts_at.tzinfo else m.starts_at.replace(tzinfo=UTC)
    at = starts - REMIND_BEFORE
    if starts <= datetime.now(UTC):
        return
    await publish_event(
        "minions.meeting.reminder",
        org_id,
        {"meeting_id": str(m.id), "starts_at": starts.astimezone(UTC).isoformat()},
        session=session,
        deliver_at=max(at, datetime.now(UTC)),
    )


async def _tell_meeting(event: str, principal: Principal, m: Meeting, to: list[str], session: AsyncSession, **extra) -> None:
    to = [u for u in dict.fromkeys(to) if u and u != principal.user_id]
    if to:
        await publish_event(
            event,
            principal.org_id,
            {"meeting_id": str(m.id), "meeting": m.title, "starts_at": m.starts_at.isoformat(), "to_user_ids": to,
             "from_name": m.created_by_name or m.created_by_email, **extra},
            session=session,
        )


async def _visible_meeting(session: AsyncSession, principal: Principal, meeting_id: uuid.UUID) -> tuple[Meeting, list[MeetingAttendee]]:
    m = await session.get(Meeting, meeting_id)
    if m is None or str(m.org_id) != principal.org_id:
        raise HTTPException(404, "meeting not found")
    people = (await _attendees(session, [m.id])).get(m.id, [])
    if not (_sees_all(principal) or _organises(principal, m) or any(a.user_id == principal.user_id for a in people)):
        raise HTTPException(404, "meeting not found")
    return m, people


@meetings_router.get("", response_model=list[MeetingOut])
async def list_meetings(
    mine: bool = False,
    start: datetime | None = None,
    end: datetime | None = None,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Mine (organised or invited) for everyone; owners and admins see all
    unless `mine`. `start`/`end` narrow to meetings overlapping that window."""
    q = select(Meeting).where(Meeting.org_id == _org(principal))
    if mine or not _sees_all(principal):
        invited = select(MeetingAttendee.meeting_id).where(MeetingAttendee.user_id == principal.user_id)
        q = q.where(
            or_(
                Meeting.created_by_user_id == principal.user_id,
                and_(Meeting.created_by_user_id == "", Meeting.created_by_email == principal.email),
                Meeting.id.in_(invited),
            )
        )
    if start is not None:
        q = q.where(Meeting.ends_at > start)
    if end is not None:
        q = q.where(Meeting.starts_at < end)
    meetings = (await session.execute(q.order_by(Meeting.starts_at).limit(500))).scalars().all()
    people = await _attendees(session, [m.id for m in meetings])
    return [_out(principal, m, people.get(m.id, [])) for m in meetings]


@meetings_router.get("/invitable")
async def invitable_people(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Who I can invite: the people I look after (Minions' staff list for
    my role) and my reporting line up to the owners."""
    scope = scope_for(principal, "staff.read")
    out: dict[str, str] = {}
    if scope is not None:
        q = select(Employee).where(Employee.org_id == _org(principal), Employee.user_id != "")
        ids = await _visible_employee_ids(session, principal, scope)
        if ids is not None:
            q = q.where(Employee.id.in_(ids))
        for e in (await session.execute(q)).scalars().all():
            out[e.user_id] = e.name
    line = await approvers_for(principal.org_id, principal.user_id)
    for p in (*line.chain, *line.top):
        if p.get("user_id"):
            out.setdefault(p["user_id"], p.get("name") or p.get("email") or "")
    out.pop(principal.user_id, None)
    return sorted(({"user_id": u, "name": n} for u, n in out.items()), key=lambda p: p["name"].lower())


@meetings_router.post("", response_model=MeetingOut, status_code=201)
async def create_meeting(
    body: MeetingCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.ends_at <= body.starts_at:
        raise HTTPException(422, "ends_at must be after starts_at")
    now = datetime.now(UTC)
    meeting = Meeting(
        org_id=_org(principal),
        created_by_email=principal.email,
        created_by_user_id=principal.user_id,
        created_at=now,
        updated_at=now,
        **body.model_dump(exclude={"attendee_user_ids"}),
    )
    session.add(meeting)
    await session.flush()
    if body.attendee_user_ids:
        meeting.created_by_name = await _name_of(session, principal)
        invited = await _invite(session, principal, meeting, body.attendee_user_ids)
        await _tell_meeting("minions.meeting.invited", principal, meeting, invited, session)
    await _schedule_reminder(principal.org_id, meeting, session)
    await _sync_meeting_to_calendar(meeting)
    await session.commit()
    await session.refresh(meeting)
    return _out(principal, meeting, (await _attendees(session, [meeting.id])).get(meeting.id, []))


@meetings_router.patch("/{meeting_id}", response_model=MeetingOut)
async def update_meeting(
    meeting_id: uuid.UUID,
    body: MeetingUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    meeting, people = await _visible_meeting(session, principal, meeting_id)
    if not (_organises(principal, meeting) or _sees_all(principal)):
        raise HTTPException(403, "only whoever organised it changes it; you can accept or decline")
    changes = body.model_dump(exclude_unset=True)
    new_people = changes.pop("attendee_user_ids", None)
    moved = any(k in changes and changes[k] != getattr(meeting, k) for k in ("starts_at", "ends_at"))
    for field_name, value in changes.items():
        setattr(meeting, field_name, value)
    if meeting.ends_at <= meeting.starts_at:
        raise HTTPException(422, "ends_at must be after starts_at")
    if not meeting.created_by_name:
        meeting.created_by_name = await _name_of(session, principal)
    invited: list[str] = []
    if new_people is not None:
        invited = await _invite(session, principal, meeting, new_people)
        changes["attendee_emails"] = meeting.attendee_emails
    if invited:
        await _tell_meeting("minions.meeting.invited", principal, meeting, invited, session)
    if moved:
        # Everyone already invited hears the new time (and answers again).
        for a in people:
            if a.user_id not in invited:
                a.response = "invited"
        await _tell_meeting("minions.meeting.changed", principal, meeting, [a.user_id for a in people], session)
    if moved:
        await _schedule_reminder(principal.org_id, meeting, session)
    # Only re-sync if something Calendar actually cares about changed --
    # an org that hasn't connected Calendar yet shouldn't get a fresh
    # "not connected" error stamped on every unrelated edit.
    if changes.keys() & {"title", "starts_at", "ends_at", "attendee_emails"}:
        await _sync_meeting_to_calendar(meeting)
    meeting.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(meeting)
    return _out(principal, meeting, (await _attendees(session, [meeting.id])).get(meeting.id, []))


@meetings_router.post("/{meeting_id}/respond", response_model=MeetingOut)
async def respond_to_meeting(
    meeting_id: uuid.UUID,
    body: MeetingResponse,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """An invited member accepts or declines; the organiser is told."""
    meeting, people = await _visible_meeting(session, principal, meeting_id)
    me = next((a for a in people if a.user_id == principal.user_id), None)
    if me is None:
        raise HTTPException(403, "you aren't invited to this meeting")
    if me.response != body.response:
        me.response = body.response
        await _tell_meeting(
            "minions.meeting.answered", principal, meeting, [meeting.created_by_user_id], session,
            response=body.response, by_name=me.name or principal.email,
        )
    await session.commit()
    await session.refresh(meeting)
    return _out(principal, meeting, (await _attendees(session, [meeting.id])).get(meeting.id, []))


@meetings_router.delete("/{meeting_id}", status_code=204)
async def delete_meeting(
    meeting_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    meeting, people = await _visible_meeting(session, principal, meeting_id)
    if not (_organises(principal, meeting) or _sees_all(principal)):
        raise HTTPException(403, "only whoever organised it cancels it")
    if meeting.calendar_event_id:
        provider = await _calendar_provider(str(meeting.org_id))
        if provider is not None:
            try:
                await provider.delete_event(meeting.calendar_event_id)
            except Exception:  # noqa: BLE001 -- deleting our own record shouldn't hinge on Google's API being up
                pass
    await _tell_meeting("minions.meeting.cancelled", principal, meeting, [a.user_id for a in people], session)
    await session.delete(meeting)
    await session.commit()


@webhooks_router.post("/meeting-reminder", dependencies=[Depends(require_kernel_token)], status_code=204)
async def meeting_reminder(body: dict, session: AsyncSession = Depends(get_session)):
    """30 minutes before a meeting (scheduled by _schedule_reminder): still
    on, at the same time? Then its organiser and everyone who hasn't
    declined hear it's starting soon."""
    org_id, payload = str(body["org_id"]), body.get("payload") or {}
    await set_org_context(session, org_id)
    if not await first_delivery(session, body):
        return
    try:
        m = await session.get(Meeting, uuid.UUID(str(payload.get("meeting_id"))))
        starts = datetime.fromisoformat(str(payload.get("starts_at")))
    except (ValueError, TypeError):
        return
    if m is None or str(m.org_id) != org_id or m.starts_at.astimezone(UTC) != starts.astimezone(UTC):
        await session.commit()
        return
    people = (await _attendees(session, [m.id])).get(m.id, [])
    to = [m.created_by_user_id, *(a.user_id for a in people if a.response != "declined")]
    to = [u for u in dict.fromkeys(to) if u]
    if to:
        await publish_event(
            "minions.meeting.soon",
            org_id,
            {"meeting_id": str(m.id), "meeting": m.title, "starts_at": m.starts_at.isoformat(), "to_user_ids": to},
            session=session,
        )
    await session.commit()


@webhooks_router.post("/pos-sale", dependencies=[Depends(require_kernel_token)], status_code=204)
async def pos_sale_recorded(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to invoicing.pos_sale.recorded (see
    kernel/internal/gateway/events.go) -- attributes the sale to whichever
    employee rang it up, same event apps/inventory's pos_sale_recorded and
    apps/accounting's pos_sale_cogs already subscribe to for stock/COGS.
    Silently skipped if the cashier isn't a provisioned employee, or the
    sale carries no cashier identity at all (pre-existing sales recorded
    before this feature shipped, or return_pos_sale predating it)."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    # The kernel retries until a delivery succeeds; a repeat is skipped.
    if not await first_delivery(session, body):
        return

    invoice_number = payload.get("invoice_number") or ""
    if not invoice_number:
        return
    existing = await session.execute(
        select(EmployeeSale.id).where(EmployeeSale.org_id == org_id, EmployeeSale.invoice_number == invoice_number)
    )
    if existing.first() is not None:
        return  # already recorded -- event delivery is at-least-once

    employee = await _resolve_employee_by_identity(
        session, org_id, payload.get("cashier_user_id"), payload.get("cashier_email")
    )
    if employee is None:
        return

    session.add(
        EmployeeSale(
            org_id=org_id,
            employee_id=employee.id,
            employee_name=employee.name,
            invoice_number=invoice_number,
            amount_cents=payload.get("amount_cents", 0),
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()


async def _visible_employee_ids(session: AsyncSession, principal: Principal, scope: Scope):
    """The employees `scope` covers, by their Friday account: None for all.
    shortcut: an employee who has never signed in (no user_id yet) is seen
    only with "all" scope; People merges employees with memberships in
    plan 12.8 step 3."""
    people = await people_in(scope, principal.org_id)
    if people is None:
        return None
    rows = await session.execute(
        select(Employee.id).where(Employee.org_id == _org(principal), Employee.user_id.in_(list(people)))
    )
    return [r[0] for r in rows.all()]


@employees_router.get("", response_model=list[EmployeeOut])
async def list_employees(
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("staff.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """Staff list by role (plan 12.2): everyone, their locations or their
    team. Pay rates and wallets only for those who handle pay, and each
    person's own."""
    q = select(Employee).where(Employee.org_id == _org(principal)).order_by(Employee.name)
    ids = await _visible_employee_ids(session, principal, scope)
    if ids is not None:
        q = q.where(Employee.id.in_(ids))
    pay = scope_for(principal, "pay.read")
    sees_pay = pay is not None and pay.kind == "all"
    out = []
    for e in (await session.execute(q)).scalars().all():
        row = EmployeeOut.model_validate(e)
        if not sees_pay and e.user_id != principal.user_id:
            row = row.model_copy(
                update={"pay_rate_cents": None, "wallet_address": "", "wallet_network": "",
                        "kra_pin": "", "national_id": "", "nssf_number": "", "sha_number": ""}
            )
        out.append(row)
    return out


@employees_router.post("", response_model=EmployeeOut, status_code=201)
async def create_employee(
    body: EmployeeCreate,
    principal: Principal = Depends(get_current_principal),
    _pay: Scope = Depends(require("pay.write")),
    session: AsyncSession = Depends(get_org_session),
):
    if body.pay_frequency not in PAY_FREQUENCIES:
        raise HTTPException(422, f"pay_frequency must be one of {PAY_FREQUENCIES}")
    if body.status not in EMPLOYEE_STATUSES:
        raise HTTPException(422, f"status must be one of {EMPLOYEE_STATUSES}")
    _statutory_numbers(body)
    existing = await session.execute(
        select(Employee).where(Employee.org_id == _org(principal), Employee.email == body.email)
    )
    if existing.scalars().first() is not None:
        raise HTTPException(409, f"an employee with email {body.email!r} already exists")

    now = datetime.now(UTC)
    employee = Employee(org_id=_org(principal), created_at=now, updated_at=now, **body.model_dump())
    session.add(employee)
    await session.commit()
    await session.refresh(employee)
    return employee


async def _get_owned_employee(session: AsyncSession, principal: Principal, employee_id: uuid.UUID) -> Employee:
    employee = await session.get(Employee, employee_id)
    if employee is None or str(employee.org_id) != principal.org_id:
        raise HTTPException(404, "employee not found")
    return employee


_KRA_PIN = re.compile(r"^[AP][0-9]{9}[A-Z]$")


def _statutory_numbers(body) -> None:
    """Tidies and checks the return numbers (empty is fine until filing)."""
    body.kra_pin = body.kra_pin.strip().upper()
    if body.kra_pin and not _KRA_PIN.match(body.kra_pin):
        raise HTTPException(422, "a KRA PIN looks like A012345678Z: A or P, nine digits, a letter")
    body.national_id = body.national_id.strip()
    if body.national_id and not body.national_id.isdigit():
        raise HTTPException(422, "the ID number is digits only")
    for f in ("nssf_number", "sha_number"):
        v = getattr(body, f).strip().upper()
        if v and not v.replace("-", "").isalnum():
            raise HTTPException(422, f"the {f.split('_')[0].upper()} number is letters and digits only")
        setattr(body, f, v)


@employees_router.patch("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeCreate,
    principal: Principal = Depends(get_current_principal),
    _pay: Scope = Depends(require("pay.write")),
    session: AsyncSession = Depends(get_org_session),
):
    if body.pay_frequency not in PAY_FREQUENCIES:
        raise HTTPException(422, f"pay_frequency must be one of {PAY_FREQUENCIES}")
    if body.status not in EMPLOYEE_STATUSES:
        raise HTTPException(422, f"status must be one of {EMPLOYEE_STATUSES}")
    _statutory_numbers(body)
    employee = await _get_owned_employee(session, principal, employee_id)
    for field_name, value in body.model_dump().items():
        setattr(employee, field_name, value)
    employee.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(employee)
    return employee


@me_router.get("/wallet", response_model=WalletLinkOut)
async def get_my_wallet(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    return await _resolve_my_employee(session, principal)


@me_router.put("/wallet", response_model=WalletLinkOut)
async def set_my_wallet(
    body: WalletLinkUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The employee's own receiving address, pasted from their personal
    Acyn Wallet consumer app -- there's no partner-side lookup-by-email
    on Acyn's Partner API (payouts go to a raw address via POST
    /partners/send), so this is the only way payroll/expense payouts
    know where to send money."""
    employee = await _resolve_my_employee(session, principal)
    employee.wallet_address = body.wallet_address
    employee.wallet_network = body.wallet_network
    employee.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(employee)
    return employee


@me_router.get("/payroll", response_model=list[MyPayrollLineOut])
async def my_payroll(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Self-service read of the caller's own payroll history -- same
    self-resolve pattern as /me/wallet. No admin actions here; approve/
    pay/refresh-status stay admin-gated on the payroll_runs routes."""
    employee = await _resolve_my_employee(session, principal)
    rows = await session.execute(
        select(PayrollLine, PayrollRun)
        .join(PayrollRun, PayrollLine.payroll_run_id == PayrollRun.id)
        .where(PayrollLine.employee_id == employee.id)
        .order_by(PayrollRun.period_start.desc())
    )
    return [
        MyPayrollLineOut(
            payroll_run_id=line.payroll_run_id,
            period_start=run.period_start,
            period_end=run.period_end,
            run_status=run.status,
            gross_amount_cents=line.gross_amount_cents,
            currency=run.currency,
            line_status=line.status,
            nssf_cents=line.nssf_cents,
            shif_cents=line.shif_cents,
            levy_cents=line.levy_cents,
            paye_cents=line.paye_cents,
            net_cents=line.paid_cents,
            advance_cents=line.advance_cents,
            unpaid_days=line.unpaid_days,
            unpaid_cents=line.unpaid_cents,
        )
        for line, run in rows.all()
    ]


@expense_claims_router.get("", response_model=list[ExpenseClaimOut])
async def list_expense_claims(
    mine: bool = False,
    waiting: bool = False,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("claims.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """Claims by role: your own, your team's, your locations' or all;
    `mine` narrows to your own whatever your role. `waiting`: the ones
    waiting for your decision (owners and admins: every waiting claim,
    since they decide anything)."""
    query = select(ExpenseClaim).where(ExpenseClaim.org_id == _org(principal))
    if waiting:
        query = query.where(ExpenseClaim.status == "submitted")
        if principal.role not in ("owner", "admin"):
            query = query.where(ExpenseClaim.waiting_on_user_id == principal.user_id)
        rows = await session.execute(query.order_by(ExpenseClaim.submitted_at))
        return rows.scalars().all()
    if mine or scope.kind == "own":
        employee = await _resolve_my_employee(session, principal)
        query = query.where(ExpenseClaim.employee_id == employee.id)
    else:
        ids = await _visible_employee_ids(session, principal, scope)
        if ids is not None:
            query = query.where(ExpenseClaim.employee_id.in_(ids))
    rows = await session.execute(query.order_by(ExpenseClaim.submitted_at.desc()))
    return rows.scalars().all()


@expense_claims_router.post("", response_model=ExpenseClaimOut, status_code=201)
async def create_expense_claim(
    body: ExpenseClaimCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Self-service -- employee_id is always the caller's own resolved
    employee row, never client-supplied."""
    employee = await _resolve_my_employee(session, principal)
    fields = body.model_dump()
    # Which money paid it decides paying back; older apps send reimburse only.
    fields["paid_from"] = body.paid_from or ("own" if body.reimburse else "business")
    fields["reimburse"] = fields["paid_from"] == "own"
    if body.for_kind != "daily" and not body.for_id.strip():
        raise HTTPException(422, f"choose which {body.for_kind} it was for")
    if body.for_kind == "daily":
        fields["for_id"] = ""
    fields["float_id"] = (
        await _petty_float_for(session, principal, body.amount_cents, body.float_id) if fields["paid_from"] == "petty_cash" else None
    )
    fields.update(await _asked_first(session, principal, employee, body))
    claim = ExpenseClaim(
        org_id=_org(principal),
        employee_id=employee.id,
        status="submitted",
        submitted_at=datetime.now(UTC),
        **fields,
    )
    session.add(claim)
    await session.flush()
    await _route_claim(session, claim, employee)
    await session.commit()
    await session.refresh(claim)
    return claim


def _ask_first_above(policy: dict, role: str) -> int | None:
    """The most a role spends without asking first (0: always ask); None
    for owners and admins, who never need to."""
    if role in ("owner", "admin"):
        return None
    return int(policy.get({"team_leader": "ask_first_team_leader", "branch_manager": "ask_first_branch_manager"}.get(role, "ask_first_member"), 0))


async def _asked_first(session: AsyncSession, principal: Principal, employee: Employee, body: ExpenseClaimCreate) -> dict:
    """Spending plan part B. A claim carries the approved request it was
    spent under (a trip picked on the form is one), inheriting what it was
    for, and is flagged when its request's claims go past the approval by
    more than the tolerance. Without one, a spend over the role's
    ask-first amount (or any trip) needs an emergency reason; Guss's claims
    are for money already spent, so they're flagged, never refused."""
    request_id = body.request_id
    if request_id is None and body.for_kind == "trip":
        try:
            request_id = uuid.UUID(body.for_id)
        except ValueError:
            request_id = None
    policy = await spending_policy(principal.org_id)
    from_guss = bool(re.search(r"\(Guss [0-9a-f]{8}\)$", body.description))
    if request_id is not None:
        req = await session.get(SpendRequest, request_id)
        if req is None or req.org_id != employee.org_id or req.employee_id != employee.id:
            raise HTTPException(404, "that request isn't one of yours")
        if req.status != "approved":
            raise HTTPException(400, f"that request is '{req.status}'; claims go against an approved one")
        claimed = await session.scalar(
            select(func.coalesce(func.sum(ExpenseClaim.amount_cents), 0)).where(
                ExpenseClaim.request_id == req.id, ExpenseClaim.status.in_(("submitted", "approved", "paid"))
            )
        )
        total, most = claimed + body.amount_cents, req.amount_cents * (100 + int(policy["tolerance_pct"])) // 100
        flag = f"{(total - req.amount_cents) * 100 // req.amount_cents}% over the approved {req.amount_cents / 100:,.0f}" if total > most else ""
        return {"request_id": req.id, "for_kind": req.for_kind if req.kind == "spend" else "trip",
                "for_id": req.for_id if req.kind == "spend" else str(req.id),
                "for_label": req.for_label if req.kind == "spend" else (req.destination or req.description),
                "emergency_reason": "", "flag": flag}
    limit = _ask_first_above(policy, principal.role)
    trip = body.for_kind == "trip" and bool(policy["trips_ask_first"]) and principal.role not in ("owner", "admin")
    if not trip and (limit is None or body.amount_cents <= limit):
        return {"request_id": None, "emergency_reason": ""}
    reason = body.emergency_reason.strip()
    if from_guss and not reason:
        return {"request_id": None, "flag": "not asked first (from Guss)"}
    if not reason:
        what = "a trip" if trip else f"a spend over {limit / 100:,.0f}"
        raise HTTPException(422, f"{what} needs asking first; ask first, or say why it was an emergency")
    return {"request_id": None, "emergency_reason": reason, "flag": "not asked first"}


async def _receipt_problem(session: AsyncSession, claim: ExpenseClaim) -> str | None:
    """Why this claim can't be approved for want of a receipt, or None.
    Receipts always (spending policy); a written reason stands in only
    under the policy's amount, a few times a year per person."""
    if claim.receipt_sha:
        return None
    if claim.emergency_reason:
        return "a spend that wasn't asked first needs its receipt; ask them to add the photo"
    policy = await spending_policy(str(claim.org_id))
    under, per_year = int(policy["no_receipt_under"]), int(policy["no_receipt_per_year"])
    money = f"{under / 100:,.0f} {claim.currency}"
    if claim.amount_cents >= under:
        return f"a receipt is needed for {money} or more; ask them to add the photo"
    if not claim.no_receipt_reason.strip():
        return "no receipt and no reason; ask them to add the photo, or say why there isn't one"
    used = await session.scalar(
        select(func.count()).where(
            ExpenseClaim.employee_id == claim.employee_id,
            ExpenseClaim.id != claim.id,
            ExpenseClaim.receipt_sha == "",
            ExpenseClaim.no_receipt_reason != "",
            ExpenseClaim.status.in_(("approved", "paid")),
            ExpenseClaim.decided_at >= datetime.now(UTC) - timedelta(days=365),
        )
    )
    if used >= per_year:
        return f"they've gone without a receipt {used} times this year (the most is {per_year}); a receipt is needed"
    return None


async def _route_claim(session: AsyncSession, claim: ExpenseClaim, employee: Employee) -> None:
    # Not asked first: one level higher than usual (spending plan part B).
    await _route_request(session, claim, employee, "expense_claim", skip=1 if claim.emergency_reason else 0)


def _may_decide(who, role: str, amount_cents: int) -> bool:
    if role in ("owner", "admin"):
        return True
    limit = who.limits.get(role)
    return limit is not None and amount_cents <= limit


async def _available_approver(session: AsyncSession, org_id: str, who, amount_cents: int, skip: int = 0) -> dict | None:
    """The nearest person up the line who may decide this amount and is
    here: someone covering for them while they're away, if that person's
    limit covers it; else, if they're on approved time off today, the next
    one up. None: the owners and admins.
    shortcut: requests already waiting aren't moved when someone goes away."""
    today = local_date(datetime.now(UTC), await business_tz(org_id))
    for person in who.chain:
        if not _may_decide(who, person.get("role", ""), amount_cents):
            continue
        cover = await session.scalar(
            select(ApprovalCover).where(
                ApprovalCover.user_id == person["user_id"], ApprovalCover.starts_on <= today, ApprovalCover.ends_on >= today
            )
        )
        if cover is not None and _may_decide(who, cover.delegate_role, amount_cents):
            return {"user_id": cover.delegate_user_id, "name": cover.delegate_name, "role": cover.delegate_role}
        away = await session.scalar(
            select(TimeOff.id)
            .join(Employee, Employee.id == TimeOff.employee_id)
            .where(Employee.user_id == person["user_id"], TimeOff.status == "approved",
                   TimeOff.starts_on <= today, TimeOff.ends_on >= today)
            .limit(1)
        )
        if away is None:
            if skip:
                skip -= 1
                continue
            return person
    return None


async def _route_request(session: AsyncSession, claim, employee: Employee, kind: str, skip: int = 0) -> None:
    """Sends a waiting request (a claim, an advance) to the nearest person
    up the requester's reporting line whose limit covers it, else to the
    owners and admins, and tells them (minions.approval.needed). Published
    in `session`, so it goes out only if the request is saved."""
    who = await approvers_for(str(claim.org_id), employee.user_id)
    person = await _available_approver(session, str(claim.org_id), who, claim.amount_cents, skip)
    if person:
        claim.waiting_on_user_id = person["user_id"]
        claim.waiting_on_name = person.get("name") or person.get("email") or "your manager"
        to = [person["user_id"]]
    else:
        claim.waiting_on_user_id, claim.waiting_on_name = "", "an owner or admin"
        to = [p["user_id"] for p in who.top]
    await publish_event(
        "minions.approval.needed",
        str(claim.org_id),
        {
            "kind": kind,
            "claim_id": str(claim.id),
            "item_id": str(claim.id),
            "to_user_ids": to,
            "from_name": employee.name,
            "amount_cents": claim.amount_cents,
            "currency": claim.currency,
            "description": claim.description,
        },
        session=session,
    )


async def _get_owned_claim(session: AsyncSession, principal: Principal, claim_id: uuid.UUID) -> ExpenseClaim:
    claim = await session.get(ExpenseClaim, claim_id)
    if claim is None or str(claim.org_id) != principal.org_id:
        raise HTTPException(404, "expense claim not found")
    return claim


RECEIPT_TYPES = {"image/webp", "image/jpeg", "image/png"}
MAX_RECEIPT_BYTES = 1024 * 1024


@expense_claims_router.put("/{claim_id}/receipt", response_model=ExpenseClaimOut)
async def put_claim_receipt(
    claim_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The receipt photo, as the raw image body: only the person who made
    the claim, while it waits for a decision."""
    claim = await _get_owned_claim(session, principal, claim_id)
    me = await _resolve_my_employee(session, principal)
    if claim.employee_id != me.id:
        raise HTTPException(403, "only the person who made the claim adds its receipt")
    if claim.status != "submitted":
        raise HTTPException(400, f"claim is '{claim.status}'; receipts go on claims still waiting")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in RECEIPT_TYPES:
        raise HTTPException(415, "send a WebP, JPEG or PNG photo")
    data = await request.body()
    if not data:
        raise HTTPException(422, "the photo is empty")
    if len(data) > MAX_RECEIPT_BYTES:
        raise HTTPException(413, "the photo is over 1 MB; resize it first")
    now = datetime.now(UTC)
    receipt = await session.get(ClaimReceipt, claim.id)
    if receipt is None:
        session.add(ClaimReceipt(claim_id=claim.id, org_id=claim.org_id, content_type=content_type, data=data, updated_at=now))
    else:
        receipt.content_type, receipt.data, receipt.updated_at = content_type, data, now
    claim.receipt_sha = hashlib.sha256(data).hexdigest()[:16]
    await session.commit()
    await session.refresh(claim)
    return claim


@expense_claims_router.get("/{claim_id}/receipt")
async def get_claim_receipt(
    claim_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("claims.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """The photo, for the claimant and whoever can see their claims."""
    claim = await _get_owned_claim(session, principal, claim_id)
    if scope.kind == "own":
        me = await _resolve_my_employee(session, principal)
        if claim.employee_id != me.id:
            raise HTTPException(404, "expense claim not found")
    else:
        ids = await _visible_employee_ids(session, principal, scope)
        if ids is not None and claim.employee_id not in ids:
            raise HTTPException(404, "expense claim not found")
    receipt = await session.get(ClaimReceipt, claim.id)
    if receipt is None:
        raise HTTPException(404, "no receipt")
    return Response(
        content=receipt.data,
        media_type=receipt.content_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@expense_claims_router.patch("/{claim_id}/status", response_model=ExpenseClaimOut)
async def set_expense_claim_status(
    claim_id: uuid.UUID,
    body: ExpenseClaimStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("claims.approve")),
    session: AsyncSession = Depends(get_org_session),
):
    """Approve/reject only -- "paid" is reached exclusively through
    POST /{id}/pay, which is the only place that actually calls the
    wallet provider, so a claim can never be marked paid without money
    actually having been queued to move."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(422, "status must be 'approved' or 'rejected'")
    note = body.note.strip()
    if body.status == "rejected" and not note:
        raise HTTPException(422, "say why it's rejected, so they can fix it")
    claim = await _get_owned_claim(session, principal, claim_id)
    if claim.status != "submitted":
        raise HTTPException(400, f"claim is '{claim.status}', not 'submitted'")
    claimant = await _check_decider(session, principal, scope, claim, "claim")
    if body.status == "approved" and (problem := await _receipt_problem(session, claim)):
        raise HTTPException(400, problem)
    claim.status = body.status
    claim.decision_note = note
    claim.decided_by_name = await _name_of(session, principal)
    claim.decided_at = datetime.now(UTC)
    claim.waiting_on_user_id = claim.waiting_on_name = ""
    await publish_event(
        "minions.expense_claim.decided",
        principal.org_id,
        {
            "claim_id": str(claim.id),
            "to_user_ids": [claimant.user_id] if claimant.user_id else [],
            "status": claim.status,
            "note": note,
            "decided_by_name": claim.decided_by_name,
            "amount_cents": claim.amount_cents,
            "currency": claim.currency,
            "description": claim.description,
        },
        session=session,
    )
    await session.commit()
    await session.refresh(claim)
    return claim


async def _check_decider(session: AsyncSession, principal: Principal, scope: Scope, item, what: str) -> Employee:
    """Who may decide a request: someone over the person (their team,
    location or everyone) or the one it was sent to, never the person
    themselves (owners excepted), and within their approval limit.
    Returns the person who asked."""
    asker = await _get_owned_employee(session, principal, item.employee_id)
    # The person it was sent to (up the asker's reporting line) may decide
    # it even outside their usual team or locations.
    routed_to_me = bool(item.waiting_on_user_id) and item.waiting_on_user_id == principal.user_id
    ids = None if routed_to_me else await _visible_employee_ids(session, principal, scope)
    if ids is not None and asker.id not in ids:
        raise HTTPException(403, f"{asker.name} isn't in your team or locations; ask {who_can('claims.approve', principal.role)}")
    if asker.user_id == principal.user_id and principal.role != "owner":
        raise HTTPException(403, f"nobody decides their own {what}; ask {who_can('claims.approve', principal.role)}")
    limits = (await approvers_for(principal.org_id, asker.user_id)).limits
    limit = None if principal.role in ("owner", "admin") else limits.get(principal.role)
    if limit is not None and item.amount_cents > limit:
        raise HTTPException(
            403, f"above your approval limit ({limit // 100:,}); ask {who_can('claims.approve', principal.role)}"
        )
    return asker


async def _name_of(session: AsyncSession, principal: Principal) -> str:
    """The person's name as Minions knows it, else their email."""
    rows = await session.execute(
        select(Employee.name).where(Employee.org_id == _org(principal), Employee.user_id == principal.user_id)
    )
    return rows.scalars().first() or principal.email


@expense_claims_router.post("/{claim_id}/resend", response_model=ExpenseClaimOut)
async def resend_expense_claim(
    claim_id: uuid.UUID,
    body: ExpenseClaimResend,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """A rejected claim, fixed by the person who made it and sent again:
    it waits once more, routed afresh (the amount may have changed)."""
    claim = await _get_owned_claim(session, principal, claim_id)
    me = await _resolve_my_employee(session, principal)
    if claim.employee_id != me.id:
        raise HTTPException(403, "only the person who made the claim sends it again")
    if claim.status != "rejected":
        raise HTTPException(400, f"claim is '{claim.status}'; only a rejected claim is sent again")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(claim, field, value)
    if body.reimburse is not None:
        claim.paid_from = "own" if body.reimburse else ("business" if claim.paid_from == "own" else claim.paid_from)
    claim.status = "submitted"
    claim.submitted_at = datetime.now(UTC)
    claim.decision_note = claim.decided_by_name = ""
    claim.decided_at = None
    await _route_claim(session, claim, me)
    await session.commit()
    await session.refresh(claim)
    return claim


@expense_claims_router.post("/{claim_id}/pay", response_model=ExpenseClaimOut)
async def pay_expense_claim(
    claim_id: uuid.UUID,
    body: ExpenseClaimPay | None = None,
    principal: Principal = Depends(get_current_principal),
    _pay: Scope = Depends(require("pay.write")),
    session: AsyncSession = Depends(get_org_session),
):
    claim = await _get_owned_claim(session, principal, claim_id)
    if claim.status != "approved":
        raise HTTPException(400, f"claim is '{claim.status}', not 'approved'")
    pay = body or ExpenseClaimPay()
    if claim.float_id:
        raise HTTPException(400, "this came out of petty cash; its holder confirms it under Petty cash")
    if claim.reimburse and claim.request_id:
        trip = await session.get(SpendRequest, claim.request_id)
        if trip and trip.advance_paid_at and trip.status == "approved":
            raise HTTPException(400, "this comes out of the trip's advance; settle the trip instead")
    # The business's own money (petty cash, its M-Pesa, card or bank):
    # confirming it was paid books it; there's nothing to pay back.
    if not claim.reimburse and pay.method == "crypto":
        raise HTTPException(422, "say how the business paid: M-Pesa, bank or cash")
    reference = pay.reference.strip()
    if pay.method in ("mpesa", "bank") and not reference:
        raise HTTPException(422, "add the M-Pesa code or bank reference")
    employee = await _get_owned_employee(session, principal, claim.employee_id)
    if pay.method == "crypto":
        if not employee.wallet_address:
            raise HTTPException(400, f"{employee.name} hasn't connected a wallet yet")
        provider = await _provider(principal)
        await provider.request_payout(
            to_address=employee.wallet_address,
            currency=claim.currency,
            amount=f"{claim.amount_cents / 100:.2f}",
            network=employee.wallet_network,
            reason=f"Expense claim: {claim.description}",
        )
    claim.status = "paid"
    claim.paid_method, claim.paid_reference, claim.paid_at = pay.method, reference, datetime.now(UTC)
    # The books: a claim Guss booked as owed (its description ends "(Guss
    # <id>)") clears 2150 Owed to staff; any other is a shop expense now.
    # Saved with the claim's new status, in its transaction (plan 19.2).
    await publish_event(
        "minions.expense_claim.paid",
        principal.org_id,
        {
            "claim_id": str(claim.id),
            # Paid back: they're told. The business's own money: nothing to tell.
            "to_user_ids": [employee.user_id] if employee.user_id and claim.reimburse else [],
            "method": pay.method,
            "reference": reference,
            "amount_cents": claim.amount_cents,
            "currency": claim.currency,
            "owed_booked": bool(re.search(r"\(Guss [0-9a-f]{8}\)$", claim.description)),
            "description": claim.description,
        },
        session=session,
    )
    await session.commit()
    await session.refresh(claim)
    return claim


@expense_claims_router.post("/{claim_id}/withdraw", response_model=ExpenseClaimOut)
async def withdraw_expense_claim(
    claim_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The person who made a claim takes it back while it still waits."""
    claim = await _get_owned_claim(session, principal, claim_id)
    me = await _resolve_my_employee(session, principal)
    if claim.employee_id != me.id:
        raise HTTPException(403, "only the person who made the claim withdraws it")
    if claim.status != "submitted":
        raise HTTPException(400, f"claim is '{claim.status}'; only a waiting claim can be withdrawn")
    claim.status = "withdrawn"
    await session.commit()
    await session.refresh(claim)
    return claim


@payroll_router.get("", response_model=list[PayrollRunOut])
async def list_payroll_runs(
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(PayrollRun).where(PayrollRun.org_id == _org(principal)).order_by(PayrollRun.created_at.desc())
    )
    return [PayrollRunOut.from_model(r) for r in rows.scalars().all()]


@payroll_router.post("", response_model=PayrollRunOut, status_code=201)
async def create_payroll_run(
    body: PayrollRunCreate,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """gross_amount_cents is each employee's pay_rate_cents as-is --
    Minions has no timesheet integration, so pay_rate_cents is treated
    as a flat amount per pay_frequency cycle, not an hourly rate. A
    deployment that needs hourly-times-timesheet math can compute that
    itself and pass the result in, since there's nowhere else for it to
    come from yet."""
    if body.payout_method not in PAYOUT_METHODS:
        raise HTTPException(422, f"payout_method must be one of {PAYOUT_METHODS}")

    now = datetime.now(UTC)
    run = PayrollRun(
        org_id=_org(principal),
        period_start=body.period_start,
        period_end=body.period_end,
        payout_method=body.payout_method,
        status="draft",
        currency=body.currency,
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    await session.flush()

    for employee_id in body.employee_ids:
        employee = await _get_owned_employee(session, principal, employee_id)
        session.add(
            PayrollLine(
                org_id=_org(principal),
                payroll_run_id=run.id,
                employee_id=employee.id,
                employee_name=employee.name,
                to_address=employee.wallet_address,
                network=employee.wallet_network,
                status="pending" if employee.wallet_address else "blocked",
                **{"gross_amount_cents": employee.pay_rate_cents, **await _with_advance(session, employee, await _with_unpaid(session, employee, run))},
            )
        )
    await session.commit()
    await session.refresh(run, attribute_names=["lines"])
    return PayrollRunOut.from_model(run)


async def _get_owned_run(session: AsyncSession, principal: Principal, run_id: uuid.UUID) -> PayrollRun:
    run = await session.get(PayrollRun, run_id)
    if run is None or str(run.org_id) != principal.org_id:
        raise HTTPException(404, "payroll run not found")
    return run


@payroll_router.post("/{run_id}/approve", response_model=PayrollRunOut)
async def approve_payroll_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    run = await _get_owned_run(session, principal, run_id)
    if run.status != "draft":
        raise HTTPException(400, f"run is '{run.status}', not 'draft'")
    run.status = "approved"
    run.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(run, attribute_names=["lines"])
    return PayrollRunOut.from_model(run)


async def _with_unpaid(session: AsyncSession, employee: Employee, run: PayrollRun) -> dict:
    """The payslip after approved unpaid leave in the run's period: the pay
    less its share for those working days (pay x unpaid days / the
    period's working days), statutory deductions on what's left."""
    first, last = run.period_start.date(), run.period_end.date()
    rows = await session.execute(
        select(TimeOff.starts_on, TimeOff.ends_on).where(
            TimeOff.employee_id == employee.id, TimeOff.kind == "unpaid", TimeOff.status == "approved",
            TimeOff.starts_on <= last, TimeOff.ends_on >= first,
        )
    )
    unpaid = sum(_working_days(max(a, first), min(b, last)) for a, b in rows.all())
    period_days = _working_days(first, last)
    off = min(employee.pay_rate_cents, round(employee.pay_rate_cents * unpaid / period_days)) if unpaid and period_days else 0
    slip = _payslip(employee.pay_rate_cents - off, run.currency, run.period_end)
    return {**slip, "gross_amount_cents": employee.pay_rate_cents - off, "unpaid_days": unpaid, "unpaid_cents": off} if off else slip


async def _with_advance(session: AsyncSession, employee: Employee, slip: dict) -> dict:
    """Takes this pay's share of the person's open advance off the net:
    the amount over its months, never more than what's left of it or of
    the net. Counted as recovered only once this pay is paid out."""
    adv = await session.scalar(
        select(SalaryAdvance)
        .where(SalaryAdvance.employee_id == employee.id, SalaryAdvance.status == "paid")
        .order_by(SalaryAdvance.submitted_at)
        .limit(1)
    )
    if adv is None or adv.remaining_cents <= 0:
        return slip
    share = -(-adv.amount_cents // adv.months)  # rounded up
    take = min(share, adv.remaining_cents, slip.get("net_cents", 0))
    if take <= 0:
        return slip
    return {**slip, "net_cents": slip["net_cents"] - take, "advance_cents": take, "advance_id": adv.id}


def _payslip(gross_cents: int, currency: str, period_end: datetime) -> dict:
    """What comes off a line's gross. Kenyan statutory deductions for a run
    in KES, at the rates in force at the end of its period; other
    currencies have none yet (net = gross).
    shortcut: KES stands for Kenya; follow the business's country when
    orgs record one."""
    if currency.upper() != "KES":
        return {"net_cents": gross_cents}
    d = kenya_deductions(gross_cents, period_end.date())
    return {
        "nssf_cents": d.nssf_cents,
        "shif_cents": d.shif_cents,
        "levy_cents": d.levy_cents,
        "paye_cents": d.paye_cents,
        "net_cents": d.net_cents,
        "employer_nssf_cents": d.employer_nssf_cents,
        "employer_levy_cents": d.employer_levy_cents,
    }


@payroll_router.post("/{run_id}/pay", response_model=PayrollRunOut)
async def pay_payroll_run(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    run = await _get_owned_run(session, principal, run_id)
    if run.status != "approved":
        raise HTTPException(400, f"run is '{run.status}', not 'approved'")
    if run.payout_method == "fiat":
        # Bridge (packages/py-common/friday_common/integrations/bridge.py)
        # is exactly the right interface for this -- fiat off-ramp via
        # Acyn Wallet's own Bridge settlement is still a work in
        # progress on Acyn's side, so this is a documented stub, same
        # tier as every other unfinished integration. See INTEGRATIONS.md#bridge.
        raise HTTPException(501, "Fiat payroll isn't available yet -- see INTEGRATIONS.md#bridge")

    provider = await _provider(principal)
    await session.refresh(run, attribute_names=["lines"])
    for line in run.lines:
        if line.status != "pending":
            continue
        try:
            result = await provider.request_payout(
                to_address=line.to_address,
                currency=run.currency,
                amount=f"{line.paid_cents / 100:.2f}",  # the net: deductions go to KRA, NSSF, SHA
                network=line.network,
                reason=f"Payroll {run.id}",
            )
        except Exception:
            # Best-effort per line -- a transient failure on one
            # employee's payout shouldn't block the rest of the run.
            # Left "pending" so a retried /pay call picks it up again.
            continue
        line.status = "sent"
        line.external_id = result.get("id", "")

    run.status = "paying"
    run.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(run, attribute_names=["lines"])
    return PayrollRunOut.from_model(run)


@payroll_router.post("/{run_id}/refresh-status", response_model=PayrollRunOut)
async def refresh_payroll_run_status(
    run_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """Polls Acyn Wallet for every line that's been sent but not yet
    confirmed -- identical shape to apps/web3's refresh_transaction_status.
    Once every line has reached a terminal state (blocked/confirmed/
    failed), the run itself is marked paid, which is also the moment
    minions.payroll_run.paid fires -- Accounting's subscriber (see
    kernel/internal/gateway/events.go) posts Dr Salary Expense / Cr Cash
    for the lines that actually moved money."""
    run = await _get_owned_run(session, principal, run_id)
    provider = await _provider(principal)
    await session.refresh(run, attribute_names=["lines"])

    for line in run.lines:
        if line.status != "sent" or not line.external_id:
            continue
        result = await provider.get_payout_status(line.external_id)
        status = result.get("status", "")
        if status in ("completed", "confirmed", "success"):
            line.status = "confirmed"
        elif status in ("failed", "rejected", "cancelled"):
            line.status = "failed"
        # else: still pending on Acyn's side, leave as "sent"

    await session.flush()
    await session.refresh(run, attribute_names=["lines"])
    newly_paid = run.status != "paid" and all(l.status in ("blocked", "confirmed", "failed") for l in run.lines)
    if newly_paid:
        run.status = "paid"
        run.updated_at = datetime.now(UTC)

    if newly_paid:
        paid = [l for l in run.lines if l.status == "confirmed"]
        for line in paid:
            if line.advance_id and line.advance_cents:
                adv = await session.get(SalaryAdvance, line.advance_id)
                if adv is not None and adv.status == "paid":
                    adv.recovered_cents += line.advance_cents
                    if adv.recovered_cents >= adv.amount_cents:
                        adv.status = "recovered"
        paid_cents = sum(l.paid_cents for l in paid)
        if paid_cents > 0:
            total = lambda f: sum(getattr(l, f) for l in paid)  # noqa: E731
            # Saved with the run's new status (plan 19.2). The books take
            # the gross as salary, the net out of cash, and each deduction
            # (both shares) as owed to KRA, NSSF and SHA.
            await publish_event(
                "minions.payroll_run.paid",
                principal.org_id,
                {
                    "payroll_run_id": str(run.id),
                    "amount_cents": paid_cents,
                    "currency": run.currency,
                    "gross_cents": total("gross_amount_cents"),
                    "paye_cents": total("paye_cents"),
                    "nssf_cents": total("nssf_cents"),
                    "employer_nssf_cents": total("employer_nssf_cents"),
                    "shif_cents": total("shif_cents"),
                    "levy_cents": total("levy_cents"),
                    "employer_levy_cents": total("employer_levy_cents"),
                    "advance_cents": total("advance_cents"),
                },
                session=session,
            )
    await session.commit()
    await session.refresh(run, attribute_names=["lines"])
    return PayrollRunOut.from_model(run)


# Monthly statutory returns (HR plan phase 2): from the payslips of the
# month's payroll runs (by their period's end, in the business's calendar),
# one row per person, as CSV to copy into each authority's template:
# KRA (PAYE and Housing Levy, the P10), NSSF (Tier I and II, both shares),
# SHA (SHIF). Only for whoever sees everyone's pay.
RETURN_KINDS = ("paye", "nssf", "shif")


def _shillings(cents: int) -> str:
    return f"{cents / 100:.2f}"


@payroll_router.get("/returns.csv")
async def payroll_return_csv(
    kind: str,
    month: str,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("pay.read")),
    session: AsyncSession = Depends(get_org_session),
):
    if kind not in RETURN_KINDS:
        raise HTTPException(422, f"kind is one of {RETURN_KINDS}")
    if scope.kind != "all":
        raise HTTPException(403, "only whoever handles everyone's pay files the returns")
    try:
        first = datetime.strptime(month, "%Y-%m")
    except ValueError:
        raise HTTPException(422, "month is YYYY-MM") from None
    start, end = month_bounds(first.year, first.month, await business_tz(principal.org_id))
    rows = await session.execute(
        select(PayrollLine, PayrollRun, Employee)
        .join(PayrollRun, PayrollRun.id == PayrollLine.payroll_run_id)
        .join(Employee, Employee.id == PayrollLine.employee_id)
        .where(
            PayrollRun.org_id == _org(principal),
            PayrollRun.status != "draft",
            PayrollRun.period_end >= start,
            PayrollRun.period_end < end,
            PayrollLine.status.notin_(("blocked", "failed")),
        )
    )
    people: dict = {}
    for line, run, emp in rows.all():
        p = people.setdefault(emp.id, {"emp": emp, "lines": []})
        p["lines"].append((line, run.period_end.date()))

    out = io.StringIO()
    w = csv.writer(out)
    if kind == "paye":
        w.writerow(["KRA PIN", "Employee", "Gross pay", "NSSF", "SHIF", "Housing Levy (employee)",
                    "Housing Levy (employer)", "Taxable pay", "Tax charged", "Personal relief", "PAYE", "Note"])
    elif kind == "nssf":
        w.writerow(["ID number", "NSSF number", "KRA PIN", "Employee", "Gross pay", "Tier I (employee)",
                    "Tier II (employee)", "Tier I (employer)", "Tier II (employer)", "Total", "Note"])
    else:
        w.writerow(["ID number", "SHA number", "Employee", "Gross pay", "SHIF", "Note"])
    for p in sorted(people.values(), key=lambda x: x["emp"].name.lower()):
        emp, lines = p["emp"], p["lines"]
        s = lambda f: sum(getattr(l, f) for l, _ in lines)  # noqa: E731
        gross = s("gross_amount_cents")
        if kind == "paye":
            taxable = gross - s("nssf_cents") - s("shif_cents") - s("levy_cents")
            charged = sum(band_tax_cents(l.gross_amount_cents - l.nssf_cents - l.shif_cents - l.levy_cents, d) for l, d in lines)
            paye = s("paye_cents")
            w.writerow([emp.kra_pin, emp.name, _shillings(gross), _shillings(s("nssf_cents")), _shillings(s("shif_cents")),
                        _shillings(s("levy_cents")), _shillings(s("employer_levy_cents")), _shillings(taxable),
                        _shillings(charged), _shillings(charged - paye), _shillings(paye), "" if emp.kra_pin else "no KRA PIN"])
        elif kind == "nssf":
            t1 = t2 = 0
            for l, d in lines:
                a, b = nssf_tiers(l.gross_amount_cents, d) if l.nssf_cents else (0, 0)
                t1, t2 = t1 + a, t2 + b
            missing = ", ".join(n for n, v in (("ID", emp.national_id), ("NSSF number", emp.nssf_number)) if not v)
            w.writerow([emp.national_id, emp.nssf_number, emp.kra_pin, emp.name, _shillings(gross), _shillings(t1),
                        _shillings(t2), _shillings(t1), _shillings(t2), _shillings(2 * (t1 + t2)),
                        f"no {missing}" if missing else ""])
        else:
            missing = ", ".join(n for n, v in (("ID", emp.national_id), ("SHA number", emp.sha_number)) if not v)
            w.writerow([emp.national_id, emp.sha_number, emp.name, _shillings(gross), _shillings(s("shif_cents")),
                        f"no {missing}" if missing else ""])
    return Response(
        content=out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{kind}-{month}.csv"'},
    )


# Cover while away (HR plan phase 3): an approver names who decides for
# them between two dates; requests skip someone on approved time off.
APPROVER_ROLES = ("team_leader", "branch_manager", "admin", "owner")


@me_router.get("/cover")
async def my_cover(principal: Principal = Depends(get_current_principal), session: AsyncSession = Depends(get_org_session)):
    c = await session.get(ApprovalCover, (_org(principal), principal.user_id))
    if c is None or c.ends_on < datetime.now(UTC).date():
        return None
    return {"delegate_user_id": c.delegate_user_id, "delegate_name": c.delegate_name,
            "starts_on": c.starts_on.isoformat(), "ends_on": c.ends_on.isoformat()}


@me_router.put("/cover")
async def set_my_cover(
    body: CoverSet,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Approvers only; the cover must be able to approve too, and not you."""
    if principal.role not in APPROVER_ROLES:
        raise HTTPException(403, "only people who approve requests name cover")
    if body.ends_on < body.starts_on or (body.ends_on - body.starts_on).days > 92:
        raise HTTPException(422, "pick a last day on or after the first, at most three months on")
    if body.delegate_user_id == principal.user_id:
        raise HTTPException(422, "choose someone else")
    person = await person_in_business(principal.org_id, user_id=body.delegate_user_id)
    if person is None or person.get("role") not in APPROVER_ROLES:
        raise HTTPException(422, "your cover must be a team leader, manager, admin or owner here")
    c = await session.get(ApprovalCover, (_org(principal), principal.user_id))
    if c is None:
        c = ApprovalCover(org_id=_org(principal), user_id=principal.user_id, created_at=datetime.now(UTC))
        session.add(c)
    c.delegate_user_id, c.delegate_name, c.delegate_role = person["user_id"], person.get("name") or person["email"], person["role"]
    c.starts_on, c.ends_on = body.starts_on, body.ends_on
    await publish_event(
        "minions.cover.set",
        principal.org_id,
        {"to_user_ids": [person["user_id"]], "from_name": await _name_of(session, principal),
         "description": f"{body.starts_on.day} {body.starts_on.strftime('%b')} to {body.ends_on.day} {body.ends_on.strftime('%b')}"},
        session=session,
    )
    await session.commit()
    return {"delegate_user_id": c.delegate_user_id, "delegate_name": c.delegate_name,
            "starts_on": c.starts_on.isoformat(), "ends_on": c.ends_on.isoformat()}


@me_router.delete("/cover", status_code=204)
async def end_my_cover(principal: Principal = Depends(get_current_principal), session: AsyncSession = Depends(get_org_session)):
    c = await session.get(ApprovalCover, (_org(principal), principal.user_id))
    if c is not None:
        await session.delete(c)
        await session.commit()


app.include_router(employees_router)
app.include_router(me_router)
app.include_router(expense_claims_router)
app.include_router(payroll_router)
app.include_router(employee_sales_router)
app.include_router(meetings_router)
app.include_router(webhooks_router)



# Salary advances (HR plan phase 2): part of next pay, early. Asked for
# like a claim and routed up the reporting line; paid like one; taken back
# from the next 1-3 payslips (owner defaults: at most half of one pay, one
# open at a time).
advances_router = APIRouter(prefix="/salary_advances", tags=["salary-advances"])
OPEN_ADVANCE = ("submitted", "approved", "paid")


async def _get_owned_advance(session: AsyncSession, principal: Principal, advance_id: uuid.UUID) -> SalaryAdvance:
    adv = await session.get(SalaryAdvance, advance_id)
    if adv is None or str(adv.org_id) != principal.org_id:
        raise HTTPException(404, "advance not found")
    return adv


@advances_router.get("", response_model=list[SalaryAdvanceOut])
async def list_advances(
    mine: bool = False,
    waiting: bool = False,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("claims.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """Like claims: mine, waiting for me, or whose I can see."""
    q = select(SalaryAdvance).where(SalaryAdvance.org_id == _org(principal))
    if waiting:
        q = q.where(SalaryAdvance.status == "submitted")
        if principal.role not in ("owner", "admin"):
            q = q.where(SalaryAdvance.waiting_on_user_id == principal.user_id)
    elif mine or scope.kind == "own":
        me = await _resolve_my_employee(session, principal)
        q = q.where(SalaryAdvance.employee_id == me.id)
    else:
        ids = await _visible_employee_ids(session, principal, scope)
        if ids is not None:
            q = q.where(SalaryAdvance.employee_id.in_(ids))
    return (await session.execute(q.order_by(SalaryAdvance.submitted_at.desc()))).scalars().all()


@advances_router.post("", response_model=SalaryAdvanceOut, status_code=201)
async def ask_for_advance(
    body: SalaryAdvanceCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Mine only. At most half of one pay, and one open at a time."""
    me = await _resolve_my_employee(session, principal)
    if me.pay_rate_cents <= 0:
        raise HTTPException(400, "your pay isn't set up yet; ask whoever handles pay")
    cap = me.pay_rate_cents // 2
    if body.amount_cents > cap:
        raise HTTPException(422, f"an advance is at most half of your pay ({cap // 100:,})")
    open_one = await session.scalar(
        select(SalaryAdvance.id).where(SalaryAdvance.employee_id == me.id, SalaryAdvance.status.in_(OPEN_ADVANCE)).limit(1)
    )
    if open_one is not None:
        raise HTTPException(409, "you already have an advance open; it needs paying back first")
    adv = SalaryAdvance(
        org_id=_org(principal),
        employee_id=me.id,
        description=body.description.strip(),
        amount_cents=body.amount_cents,
        currency=await _business_currency(session, principal, me),
        months=body.months,
        status="submitted",
        submitted_at=datetime.now(UTC),
    )
    session.add(adv)
    await session.flush()
    await _route_request(session, adv, me, "salary_advance")
    await session.commit()
    await session.refresh(adv)
    return adv


async def _business_currency(session: AsyncSession, principal: Principal, me: Employee) -> str:
    """The currency the person is paid in: their latest payroll run's,
    else KES. shortcut: read the business's currency once Minions can."""
    run_currency = await session.scalar(
        select(PayrollRun.currency)
        .join(PayrollLine, PayrollLine.payroll_run_id == PayrollRun.id)
        .where(PayrollLine.employee_id == me.id)
        .order_by(PayrollRun.period_end.desc())
        .limit(1)
    )
    return run_currency or "KES"


@advances_router.post("/{advance_id}/withdraw", response_model=SalaryAdvanceOut)
async def withdraw_advance(
    advance_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    adv = await _get_owned_advance(session, principal, advance_id)
    me = await _resolve_my_employee(session, principal)
    if adv.employee_id != me.id:
        raise HTTPException(403, "only the person who asked takes it back")
    if adv.status != "submitted":
        raise HTTPException(400, f"the advance is '{adv.status}'; only a waiting one is taken back")
    adv.status = "withdrawn"
    adv.waiting_on_user_id = adv.waiting_on_name = ""
    await session.commit()
    await session.refresh(adv)
    return adv


@advances_router.patch("/{advance_id}/status", response_model=SalaryAdvanceOut)
async def decide_advance(
    advance_id: uuid.UUID,
    body: ExpenseClaimStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("claims.approve")),
    session: AsyncSession = Depends(get_org_session),
):
    """Approve, or reject with a reason; same rules as a claim."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(422, "status must be 'approved' or 'rejected'")
    note = body.note.strip()
    if body.status == "rejected" and not note:
        raise HTTPException(422, "say why it's rejected")
    adv = await _get_owned_advance(session, principal, advance_id)
    if adv.status != "submitted":
        raise HTTPException(400, f"the advance is '{adv.status}', not waiting")
    asker = await _check_decider(session, principal, scope, adv, "advance")
    adv.status = body.status
    adv.decision_note = note
    adv.decided_by_name = await _name_of(session, principal)
    adv.decided_at = datetime.now(UTC)
    adv.waiting_on_user_id = adv.waiting_on_name = ""
    await publish_event(
        "minions.salary_advance.decided",
        principal.org_id,
        {
            "advance_id": str(adv.id),
            "to_user_ids": [asker.user_id] if asker.user_id else [],
            "status": adv.status,
            "note": note,
            "decided_by_name": adv.decided_by_name,
            "amount_cents": adv.amount_cents,
            "currency": adv.currency,
        },
        session=session,
    )
    await session.commit()
    await session.refresh(adv)
    return adv


@advances_router.post("/{advance_id}/pay", response_model=SalaryAdvanceOut)
async def pay_advance(
    advance_id: uuid.UUID,
    body: ExpenseClaimPay,
    principal: Principal = Depends(get_current_principal),
    _pay: Scope = Depends(require("pay.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Pays an approved advance (M-Pesa, bank, cash, or crypto through the
    wallet); the books hold it as owed by the person until recovered."""
    adv = await _get_owned_advance(session, principal, advance_id)
    if adv.status != "approved":
        raise HTTPException(400, f"the advance is '{adv.status}', not 'approved'")
    reference = body.reference.strip()
    if body.method in ("mpesa", "bank") and not reference:
        raise HTTPException(422, "add the M-Pesa code or bank reference")
    employee = await _get_owned_employee(session, principal, adv.employee_id)
    if body.method == "crypto":
        if not employee.wallet_address:
            raise HTTPException(400, f"{employee.name} hasn't connected a wallet yet")
        provider = await _provider(principal)
        await provider.request_payout(
            to_address=employee.wallet_address,
            currency=adv.currency,
            amount=f"{adv.amount_cents / 100:.2f}",
            network=employee.wallet_network,
            reason=f"Salary advance {adv.id}",
        )
    adv.status = "paid"
    adv.paid_method, adv.paid_reference, adv.paid_at = body.method, reference, datetime.now(UTC)
    await publish_event(
        "minions.salary_advance.paid",
        principal.org_id,
        {
            "advance_id": str(adv.id),
            "to_user_ids": [employee.user_id] if employee.user_id else [],
            "amount_cents": adv.amount_cents,
            "currency": adv.currency,
            "method": body.method,
            "months": adv.months,
        },
        session=session,
    )
    await session.commit()
    await session.refresh(adv)
    return adv


app.include_router(advances_router)



# Time off (HR plan phase 3): asked for, decided up the reporting line
# like a claim, shown on calendars. Annual leave: 21 working days a year
# (owner default; Kenya's minimum); sick and unpaid are recorded.
time_off_router = APIRouter(prefix="/time_off", tags=["time-off"])
ANNUAL_DAYS = 21
KIND_WORDS = {"annual": "Annual leave", "sick": "Sick leave", "unpaid": "Unpaid leave"}


def _working_days(start: date, end: date) -> int:
    """Monday to Friday from start to end, both included.
    shortcut: public holidays count as working days; subtract them when
    Friday keeps a holiday calendar."""
    days, d = 0, start
    while d <= end:
        days += d.weekday() < 5
        d += timedelta(days=1)
    return days


async def _annual_taken(session: AsyncSession, employee_id: uuid.UUID, year: int, but: uuid.UUID | None = None) -> int:
    """Approved and waiting annual leave days starting in `year`."""
    q = select(func.coalesce(func.sum(TimeOff.days), 0)).where(
        TimeOff.employee_id == employee_id,
        TimeOff.kind == "annual",
        TimeOff.status.in_(("submitted", "approved")),
        TimeOff.starts_on >= date(year, 1, 1),
        TimeOff.starts_on < date(year + 1, 1, 1),
    )
    if but is not None:
        q = q.where(TimeOff.id != but)
    return int(await session.scalar(q) or 0)


@time_off_router.get("/balance")
async def time_off_balance(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """My annual leave this year: allowed, taken or asked for, left; and
    sick days taken."""
    me = await _resolve_my_employee(session, principal)
    year = datetime.now(UTC).year
    taken = await _annual_taken(session, me.id, year)
    sick = int(
        await session.scalar(
            select(func.coalesce(func.sum(TimeOff.days), 0)).where(
                TimeOff.employee_id == me.id, TimeOff.kind == "sick", TimeOff.status == "approved",
                TimeOff.starts_on >= date(year, 1, 1),
            )
        )
        or 0
    )
    return {"year": year, "annual_days": ANNUAL_DAYS, "annual_taken": taken, "annual_left": max(0, ANNUAL_DAYS - taken), "sick_taken": sick}


@time_off_router.get("", response_model=list[TimeOffOut])
async def list_time_off(
    mine: bool = False,
    waiting: bool = False,
    start: date | None = None,
    end: date | None = None,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("claims.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """Mine, waiting for me, or whose I can see (a team leader's team, a
    manager's locations, everyone for owners). `start`/`end` narrow to
    time off overlapping those days (calendars), with whose it is."""
    q = select(TimeOff, Employee.name).join(Employee, Employee.id == TimeOff.employee_id).where(TimeOff.org_id == _org(principal))
    if waiting:
        q = q.where(TimeOff.status == "submitted")
        if principal.role not in ("owner", "admin"):
            q = q.where(TimeOff.waiting_on_user_id == principal.user_id)
    elif mine or scope.kind == "own":
        me = await _resolve_my_employee(session, principal)
        q = q.where(TimeOff.employee_id == me.id)
    else:
        ids = await _visible_employee_ids(session, principal, scope)
        if ids is not None:
            q = q.where(TimeOff.employee_id.in_(ids))
    if start is not None:
        q = q.where(TimeOff.ends_on >= start)
    if end is not None:
        q = q.where(TimeOff.starts_on <= end)
    rows = await session.execute(q.order_by(TimeOff.starts_on))
    return [TimeOffOut.model_validate(t).model_copy(update={"employee_name": name}) for t, name in rows.all()]


@time_off_router.post("", response_model=TimeOffOut, status_code=201)
async def ask_for_time_off(
    body: TimeOffCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.ends_on < body.starts_on:
        raise HTTPException(422, "the last day is before the first")
    if (body.ends_on - body.starts_on).days > 92:
        raise HTTPException(422, "at most three months at a time; ask whoever handles pay for longer")
    days = _working_days(body.starts_on, body.ends_on)
    if days == 0:
        raise HTTPException(422, "those days are a weekend; nothing to ask for")
    me = await _resolve_my_employee(session, principal)
    overlap = await session.scalar(
        select(TimeOff.id).where(
            TimeOff.employee_id == me.id, TimeOff.status.in_(("submitted", "approved")),
            TimeOff.starts_on <= body.ends_on, TimeOff.ends_on >= body.starts_on,
        ).limit(1)
    )
    if overlap is not None:
        raise HTTPException(409, "you already have time off asked for or approved on some of those days")
    if body.kind == "annual":
        left = ANNUAL_DAYS - await _annual_taken(session, me.id, body.starts_on.year)
        if days > left:
            raise HTTPException(422, f"that's {days} working days and you have {max(0, left)} annual days left this year; ask for the rest as unpaid")
    dm = lambda d: f"{d.day} {d.strftime('%b')}"  # noqa: E731  ("3 Dec")
    a_, b_ = body.starts_on, body.ends_on
    span = dm(a_) if a_ == b_ else (f"{a_.day}-{dm(b_)}" if (a_.year, a_.month) == (b_.year, b_.month) else f"{dm(a_)} - {dm(b_)}")
    t = TimeOff(
        org_id=_org(principal),
        employee_id=me.id,
        kind=body.kind,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
        days=days,
        note=body.note.strip(),
        description=f"{KIND_WORDS[body.kind]}, {span}, {days} {'day' if days == 1 else 'days'}"
        + (f": {body.note.strip()}" if body.note.strip() else ""),
        status="submitted",
        submitted_at=datetime.now(UTC),
    )
    session.add(t)
    await session.flush()
    await _route_request(session, t, me, "time_off")
    await session.commit()
    await session.refresh(t)
    return t


@time_off_router.post("/{time_off_id}/withdraw", response_model=TimeOffOut)
async def withdraw_time_off(
    time_off_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Mine, while it waits or before it starts."""
    t = await session.get(TimeOff, time_off_id)
    if t is None or str(t.org_id) != principal.org_id:
        raise HTTPException(404, "time off not found")
    me = await _resolve_my_employee(session, principal)
    if t.employee_id != me.id:
        raise HTTPException(403, "only the person who asked takes it back")
    if t.status not in ("submitted", "approved") or (t.status == "approved" and t.starts_on <= datetime.now(UTC).date()):
        raise HTTPException(400, "only time off that's waiting or hasn't started is taken back")
    t.status = "withdrawn"
    t.waiting_on_user_id = t.waiting_on_name = ""
    await session.commit()
    await session.refresh(t)
    return t


@time_off_router.patch("/{time_off_id}/status", response_model=TimeOffOut)
async def decide_time_off(
    time_off_id: uuid.UUID,
    body: ExpenseClaimStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("claims.approve")),
    session: AsyncSession = Depends(get_org_session),
):
    """Approve, or turn down with a reason; same rules as a claim."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(422, "status must be 'approved' or 'rejected'")
    note = body.note.strip()
    if body.status == "rejected" and not note:
        raise HTTPException(422, "say why, so they can plan around it")
    t = await session.get(TimeOff, time_off_id)
    if t is None or str(t.org_id) != principal.org_id:
        raise HTTPException(404, "time off not found")
    if t.status != "submitted":
        raise HTTPException(400, f"this is '{t.status}', not waiting")
    asker = await _check_decider(session, principal, scope, t, "time off")
    t.status = body.status
    t.decision_note = note
    t.decided_by_name = await _name_of(session, principal)
    t.decided_at = datetime.now(UTC)
    t.waiting_on_user_id = t.waiting_on_name = ""
    await publish_event(
        "minions.time_off.decided",
        principal.org_id,
        {
            "time_off_id": str(t.id),
            "to_user_ids": [asker.user_id] if asker.user_id else [],
            "status": t.status,
            "note": note,
            "decided_by_name": t.decided_by_name,
            "description": t.description,
        },
        session=session,
    )
    await session.commit()
    await session.refresh(t)
    return t


app.include_router(time_off_router)

# Who's in today (presence.py): its own file, so it rarely meets other changes.
from .presence import router as presence_router  # noqa: E402

app.include_router(presence_router)

# Announcements (announcements.py), in its own file like presence.py.
from .announcements import router as announcements_router  # noqa: E402

app.include_router(announcements_router)


# Asking first (spending plan part B, Friday Host docs/SPENDING-PLAN.md):
# a spend request, or a trip with an optional cash advance, routed up the
# reporting line like a claim. Claims go against it; a trip is closed by
# settling its advance against its claims.
spend_router = APIRouter(prefix="/spend_requests", tags=["spend-requests"])


async def _get_owned_request(session: AsyncSession, principal: Principal, request_id: uuid.UUID) -> SpendRequest:
    req = await session.get(SpendRequest, request_id)
    if req is None or str(req.org_id) != principal.org_id:
        raise HTTPException(404, "request not found")
    return req


@spend_router.get("", response_model=list[SpendRequestOut])
async def list_spend_requests(
    mine: bool = False,
    waiting: bool = False,
    open: bool = False,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("claims.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """Like claims: mine, waiting for me, or whose I can see. `open`: the
    approved ones still taking claims (the claim form's picker)."""
    q = select(SpendRequest).where(SpendRequest.org_id == _org(principal))
    if open:
        q = q.where(SpendRequest.status == "approved")
    if waiting:
        q = q.where(SpendRequest.status == "submitted")
        if principal.role not in ("owner", "admin"):
            q = q.where(SpendRequest.waiting_on_user_id == principal.user_id)
    elif mine or scope.kind == "own":
        me = await _resolve_my_employee(session, principal)
        q = q.where(SpendRequest.employee_id == me.id)
    else:
        ids = await _visible_employee_ids(session, principal, scope)
        if ids is not None:
            q = q.where(SpendRequest.employee_id.in_(ids))
    return (await session.execute(q.order_by(SpendRequest.submitted_at.desc()))).scalars().all()


@spend_router.post("", response_model=SpendRequestOut, status_code=201)
async def ask_first(
    body: SpendRequestCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Mine only. A trip says where and when; its advance is at most its
    estimate."""
    me = await _resolve_my_employee(session, principal)
    if body.kind == "spend" and body.for_kind not in ("daily", "trip") and not body.for_id.strip():
        raise HTTPException(422, f"choose which {body.for_kind} it's for")
    if body.kind == "trip":
        if not body.destination.strip() or body.starts_on is None or body.ends_on is None:
            raise HTTPException(422, "say where the trip is to and when")
        if body.ends_on < body.starts_on:
            raise HTTPException(422, "the trip ends before it starts")
        if body.advance_cents > body.amount_cents:
            raise HTTPException(422, "the cash up front can't be more than the trip's estimate")
    elif body.advance_cents:
        raise HTTPException(422, "only a trip takes cash up front")
    fields = body.model_dump()
    if body.kind == "trip" or body.for_kind in ("daily", "trip"):
        fields.update(for_kind="trip" if body.kind == "trip" else "daily", for_id="", for_label="")
    fields.update(description=body.description.strip(), destination=body.destination.strip())
    req = SpendRequest(
        org_id=_org(principal),
        employee_id=me.id,
        currency=await _business_currency(session, principal, me),
        status="submitted",
        submitted_at=datetime.now(UTC),
        **fields,
    )
    session.add(req)
    await session.flush()
    await _route_request(session, req, me, "trip" if req.kind == "trip" else "spend_request")
    await session.commit()
    await session.refresh(req)
    return req


@spend_router.post("/{request_id}/withdraw", response_model=SpendRequestOut)
async def withdraw_spend_request(
    request_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    req = await _get_owned_request(session, principal, request_id)
    me = await _resolve_my_employee(session, principal)
    if req.employee_id != me.id:
        raise HTTPException(403, "only the person who asked takes it back")
    if req.status != "submitted":
        raise HTTPException(400, f"the request is '{req.status}'; only a waiting one is taken back")
    req.status = "withdrawn"
    req.waiting_on_user_id = req.waiting_on_name = ""
    await session.commit()
    await session.refresh(req)
    return req


@spend_router.patch("/{request_id}/status", response_model=SpendRequestOut)
async def decide_spend_request(
    request_id: uuid.UUID,
    body: ExpenseClaimStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("claims.approve")),
    session: AsyncSession = Depends(get_org_session),
):
    """Approve, or reject with a reason; same rules as a claim."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(422, "status must be 'approved' or 'rejected'")
    note = body.note.strip()
    if body.status == "rejected" and not note:
        raise HTTPException(422, "say why it's rejected")
    req = await _get_owned_request(session, principal, request_id)
    if req.status != "submitted":
        raise HTTPException(400, f"the request is '{req.status}', not waiting")
    asker = await _check_decider(session, principal, scope, req, "request")
    req.status = body.status
    req.decision_note = note
    req.decided_by_name = await _name_of(session, principal)
    req.decided_at = datetime.now(UTC)
    req.waiting_on_user_id = req.waiting_on_name = ""
    await publish_event(
        "minions.spend_request.decided",
        principal.org_id,
        {
            "request_id": str(req.id),
            "kind": req.kind,
            "to_user_ids": [asker.user_id] if asker.user_id else [],
            "status": req.status,
            "note": note,
            "decided_by_name": req.decided_by_name,
            "amount_cents": req.amount_cents,
            "currency": req.currency,
            "description": req.destination or req.description,
        },
        session=session,
    )
    await session.commit()
    await session.refresh(req)
    return req


@spend_router.post("/{request_id}/advance", response_model=SpendRequestOut)
async def pay_trip_advance(
    request_id: uuid.UUID,
    body: ExpenseClaimPay,
    principal: Principal = Depends(get_current_principal),
    _pay: Scope = Depends(require("pay.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Pays an approved trip's cash up front; the books hold it as owed by
    the person (1210 Staff advances) until the trip is settled."""
    req = await _get_owned_request(session, principal, request_id)
    if req.kind != "trip" or req.advance_cents <= 0:
        raise HTTPException(400, "this request has no cash up front")
    if req.status != "approved" or req.advance_paid_at:
        raise HTTPException(400, "only an approved trip's advance is paid, once")
    if body.method == "crypto":
        raise HTTPException(422, "pay a trip advance by M-Pesa, bank or cash")
    reference = body.reference.strip()
    if body.method in ("mpesa", "bank") and not reference:
        raise HTTPException(422, "add the M-Pesa code or bank reference")
    employee = await _get_owned_employee(session, principal, req.employee_id)
    req.advance_method, req.advance_reference, req.advance_paid_at = body.method, reference, datetime.now(UTC)
    await publish_event(
        "minions.trip_advance.paid",
        principal.org_id,
        {
            "advance_id": str(req.id),
            "to_user_ids": [employee.user_id] if employee.user_id else [],
            "amount_cents": req.advance_cents,
            "currency": req.currency,
            "method": body.method,
            "description": f"Trip advance: {req.destination}",
        },
        session=session,
    )
    await session.commit()
    await session.refresh(req)
    return req


@spend_router.post("/{request_id}/settle", response_model=SpendRequestOut)
async def settle_trip(
    request_id: uuid.UUID,
    body: TripSettle,
    principal: Principal = Depends(get_current_principal),
    _pay: Scope = Depends(require("pay.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Closes an approved request. A trip whose advance was paid is
    squared: its approved own-money claims are covered by the advance
    (marked paid); what's left comes back (cash, M-Pesa, bank) or off the
    next pay, and an overspend is paid to the person. Its waiting claims
    are decided first."""
    req = await _get_owned_request(session, principal, request_id)
    if req.status != "approved":
        raise HTTPException(400, f"the request is '{req.status}'; only an approved one is closed")
    now = datetime.now(UTC)
    if req.advance_paid_at:
        claims = (await session.execute(
            select(ExpenseClaim).where(ExpenseClaim.request_id == req.id, ExpenseClaim.reimburse,
                                       ExpenseClaim.status.in_(("submitted", "approved")))
        )).scalars().all()
        if any(c.status == "submitted" for c in claims):
            raise HTTPException(400, "decide the trip's waiting claims first")
        spent = sum(c.amount_cents for c in claims)
        balance = req.advance_cents - spent  # > 0: they give back; < 0: they're owed
        if balance < 0 and body.method == "payroll":
            raise HTTPException(422, "they spent more than the advance; pay them the rest by M-Pesa, bank or cash")
        reference = body.reference.strip()
        if balance and body.method in ("mpesa", "bank") and not reference:
            raise HTTPException(422, "add the M-Pesa code or bank reference")
        for c in claims:
            c.status, c.paid_method, c.paid_reference, c.paid_at = "paid", "advance", f"Trip {str(req.id)[:8]}", now
        if balance > 0 and body.method == "payroll":
            # Taken off the next pay like a salary advance (still in 1210 until then).
            session.add(SalaryAdvance(
                org_id=req.org_id, employee_id=req.employee_id, description=f"Unused trip advance: {req.destination}",
                amount_cents=balance, currency=req.currency, months=1, status="paid",
                paid_method="trip", paid_reference=str(req.id), paid_at=now, submitted_at=now,
            ))
        req.spent_cents, req.settle_method = spent, body.method if balance else ""
        employee = await _get_owned_employee(session, principal, req.employee_id)
        await publish_event(
            "minions.trip.settled",
            principal.org_id,
            {
                "request_id": str(req.id),
                "to_user_ids": [employee.user_id] if employee.user_id else [],
                "advance_cents": req.advance_cents,
                "spent_cents": spent,
                "method": body.method,
                "currency": req.currency,
                "description": req.destination,
            },
            session=session,
        )
    req.status, req.closed_at = "closed", now
    await session.commit()
    await session.refresh(req)
    return req


app.include_router(spend_router)


# Petty cash (spending plan part C, Friday Host docs/SPENDING-PLAN.md): a
# fixed float per location with one holder (imprest). Every movement is a
# row, so what the holder should have is their sum. A petty cash claim is
# the slip: once approved, the holder confirms it came out of the box.
# Someone other than the holder tops it back up to the float; counts book
# what's over or short.
petty_router = APIRouter(prefix="/petty_cash", tags=["petty-cash"])


def _pays(principal: Principal) -> bool:
    return principal.role in ("owner", "admin") and not principal.via


async def _petty_view(session: AsyncSession, principal: Principal, f: PettyFloat) -> PettyFloatOut:
    out = PettyFloatOut.model_validate(f)
    if principal.user_id != f.holder_user_id and not _pays(principal):
        return out  # others see whose it is, not what's in it
    out.balance_cents = await session.scalar(
        select(func.coalesce(func.sum(PettyMove.amount_cents), 0)).where(PettyMove.float_id == f.id)
    )
    out.pending_cents = await session.scalar(
        select(func.coalesce(func.sum(ExpenseClaim.amount_cents), 0)).where(
            ExpenseClaim.float_id == f.id, ExpenseClaim.status.in_(("submitted", "approved"))
        )
    )
    moves = await session.execute(
        select(PettyMove).where(PettyMove.float_id == f.id).order_by(PettyMove.created_at.desc()).limit(20)
    )
    out.moves = [PettyMoveOut.model_validate(m) for m in moves.scalars()]
    return out


async def _get_float(session: AsyncSession, principal: Principal, float_id: uuid.UUID) -> PettyFloat:
    f = await session.get(PettyFloat, float_id)
    if f is None or str(f.org_id) != principal.org_id:
        raise HTTPException(404, "petty cash not found")
    return f


async def _holder(session: AsyncSession, principal: Principal, user_id: str) -> Employee:
    holder = await session.scalar(
        select(Employee).where(Employee.org_id == _org(principal), Employee.user_id == user_id, Employee.status == "active")
    )
    if holder is None:
        raise HTTPException(422, "the holder must be someone on the staff list who has signed in")
    return holder


async def _petty_float_for(session: AsyncSession, principal: Principal, amount_cents: int, float_id: uuid.UUID | None) -> uuid.UUID | None:
    """The float a petty cash claim came out of (the only one when there's
    one; none set up: recorded as before), at most the policy's most for
    one slip."""
    floats = (await session.execute(
        select(PettyFloat.id).where(PettyFloat.org_id == _org(principal), PettyFloat.active)
    )).scalars().all()
    if not floats:
        return None
    if float_id is None and len(floats) == 1:
        float_id = floats[0]
    if float_id not in floats:
        raise HTTPException(422, "say which petty cash it came out of")
    most = int((await spending_policy(principal.org_id))["petty_slip_max"])
    if amount_cents > most:
        raise HTTPException(422, f"petty cash pays at most {most / 100:,.0f} at a time; ask first and use the business's money")
    return float_id


async def _petty_moved(session: AsyncSession, principal: Principal, f: PettyFloat, move: PettyMove) -> None:
    """Books a top-up or a count's difference (a slip books as its claim)."""
    await publish_event(
        "minions.petty_cash.moved",
        principal.org_id,
        {"move_id": str(move.id), "float_id": str(f.id), "kind": move.kind, "amount_cents": move.amount_cents,
         "method": move.method, "currency": f.currency, "description": f.name},
        session=session,
    )


@petty_router.get("", response_model=list[PettyFloatOut])
async def list_petty_cash(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Every active float (the claim form picks one); what's in it only for
    its holder and those who pay people."""
    rows = await session.execute(
        select(PettyFloat).where(PettyFloat.org_id == _org(principal), PettyFloat.active).order_by(PettyFloat.name)
    )
    return [await _petty_view(session, principal, f) for f in rows.scalars()]


@petty_router.post("", response_model=PettyFloatOut, status_code=201)
async def create_petty_cash(
    body: PettyFloatCreate,
    principal: Principal = Depends(get_current_principal),
    _pay: Scope = Depends(require("pay.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """One float per location, its size the policy's unless given. It
    starts empty: someone other than the holder funds it (top up)."""
    holder = await _holder(session, principal, body.holder_user_id)
    f = PettyFloat(
        org_id=_org(principal), name=body.name.strip(), location_id=body.location_id, holder_user_id=holder.user_id,
        holder_name=holder.name, float_cents=body.float_cents or int((await spending_policy(principal.org_id))["petty_float"]),
        currency=await _business_currency(session, principal, holder), active=True, created_at=datetime.now(UTC),
    )
    session.add(f)
    try:
        await session.commit()
    except IntegrityError:
        raise HTTPException(409, "that location already has petty cash") from None
    return await _petty_view(session, principal, f)


@petty_router.patch("/{float_id}", response_model=PettyFloatOut)
async def update_petty_cash(
    float_id: uuid.UUID,
    body: PettyFloatUpdate,
    principal: Principal = Depends(get_current_principal),
    _pay: Scope = Depends(require("pay.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """A new holder (count it together first), a new size, or closed.
    shortcut: handing over doesn't force a count; add one if floats go missing at handovers."""
    f = await _get_float(session, principal, float_id)
    if body.holder_user_id is not None:
        holder = await _holder(session, principal, body.holder_user_id)
        f.holder_user_id, f.holder_name = holder.user_id, holder.name
    if body.float_cents is not None:
        f.float_cents = body.float_cents
    if body.active is not None:
        f.active = body.active
    await session.commit()
    return await _petty_view(session, principal, f)


@petty_router.post("/{float_id}/top_up", response_model=PettyFloatOut)
async def top_up_petty_cash(
    float_id: uuid.UUID,
    body: PettyTopUp,
    principal: Principal = Depends(get_current_principal),
    _pay: Scope = Depends(require("pay.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Back up to the float: its size less what it should hold now. By
    someone other than the holder (the standard check on petty cash)."""
    f = await _get_float(session, principal, float_id)
    if principal.user_id == f.holder_user_id:
        raise HTTPException(403, "someone other than the holder tops it up")
    reference = body.reference.strip()
    if body.method in ("mpesa", "bank") and not reference:
        raise HTTPException(422, "add the M-Pesa code or bank reference")
    balance = (await _petty_view(session, principal, f)).balance_cents or 0
    amount = f.float_cents - balance
    if amount <= 0:
        raise HTTPException(400, "it's already full")
    move = PettyMove(org_id=f.org_id, float_id=f.id, kind="top_up", amount_cents=amount, method=body.method,
                     reference=reference, by_name=await _name_of(session, principal), created_at=datetime.now(UTC))
    session.add(move)
    await session.flush()
    await _petty_moved(session, principal, f, move)
    await session.commit()
    return await _petty_view(session, principal, f)


@petty_router.post("/{float_id}/count", response_model=PettyFloatOut)
async def count_petty_cash(
    float_id: uuid.UUID,
    body: PettyCount,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The holder (or whoever pays people) counts the box. Expected: what
    it should hold less slips sent but not yet confirmed (that cash is
    already out). Over or short is booked, and short needs a reason."""
    f = await _get_float(session, principal, float_id)
    if principal.user_id != f.holder_user_id and not _pays(principal):
        raise HTTPException(403, "the holder, an owner or an admin counts it")
    view = await _petty_view(session, principal, f)
    diff = body.counted_cents - ((view.balance_cents or 0) - (view.pending_cents or 0))
    if diff < 0 and not body.note.strip():
        raise HTTPException(422, f"it's {-diff / 100:,.2f} short; say why")
    move = PettyMove(org_id=f.org_id, float_id=f.id, kind="count", amount_cents=diff, note=body.note.strip(),
                     by_name=await _name_of(session, principal), created_at=datetime.now(UTC))
    session.add(move)  # a count that agrees is kept too: it shows when it was last counted
    await session.flush()
    if diff:
        await _petty_moved(session, principal, f, move)
    await session.commit()
    return await _petty_view(session, principal, f)


@petty_router.get("/slips", response_model=list[ExpenseClaimOut])
async def petty_slips_to_confirm(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Approved petty cash claims on floats I hold (owners and admins: all)."""
    q = (
        select(ExpenseClaim)
        .join(PettyFloat, PettyFloat.id == ExpenseClaim.float_id)
        .where(ExpenseClaim.org_id == _org(principal), ExpenseClaim.status == "approved")
    )
    if not _pays(principal):
        q = q.where(PettyFloat.holder_user_id == principal.user_id)
    return (await session.execute(q.order_by(ExpenseClaim.submitted_at))).scalars().all()


@petty_router.post("/slips/{claim_id}/confirm", response_model=ExpenseClaimOut)
async def confirm_petty_slip(
    claim_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The holder confirms an approved slip came out of the box: it comes
    off what they should hold and the books take it from petty cash."""
    claim = await _get_owned_claim(session, principal, claim_id)
    if claim.float_id is None:
        raise HTTPException(400, "this claim didn't come out of petty cash")
    f = await _get_float(session, principal, claim.float_id)
    if principal.user_id != f.holder_user_id and not _pays(principal):
        raise HTTPException(403, f"{f.holder_name or 'the holder'} confirms what comes out of {f.name}")
    if claim.status != "approved":
        raise HTTPException(400, f"claim is '{claim.status}', not 'approved'")
    now = datetime.now(UTC)
    claim.status, claim.paid_method, claim.paid_at = "paid", "petty_cash", now
    session.add(PettyMove(org_id=f.org_id, float_id=f.id, kind="slip", amount_cents=-claim.amount_cents,
                          claim_id=claim.id, by_name=await _name_of(session, principal), created_at=now))
    await publish_event(
        "minions.expense_claim.paid",
        principal.org_id,
        {"claim_id": str(claim.id), "to_user_ids": [], "method": "petty_cash", "reference": "",
         "amount_cents": claim.amount_cents, "currency": claim.currency,
         "owed_booked": bool(re.search(r"\(Guss [0-9a-f]{8}\)$", claim.description)), "description": claim.description},
        session=session,
    )
    await session.commit()
    await session.refresh(claim)
    return claim


app.include_router(petty_router)
