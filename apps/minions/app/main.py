import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_integration_config,
    get_org_session,
    require_role,
    resource,
)
from friday_common.integrations import AcynWalletProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    EMPLOYEE_STATUSES,
    EXPENSE_CLAIM_STATUSES,
    PAY_FREQUENCIES,
    PAYOUT_METHODS,
    PAYROLL_RUN_STATUSES,
    Employee,
    ExpenseClaim,
    PayrollLine,
    PayrollRun,
)
from .schemas import (
    EmployeeCreate,
    EmployeeOut,
    ExpenseClaimCreate,
    ExpenseClaimOut,
    ExpenseClaimStatusUpdate,
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


async def _provider(principal: Principal) -> AcynWalletProvider:
    config = await get_integration_config(principal.org_id, "acyn_wallet")
    if not config.get("api_key"):
        raise HTTPException(400, "Acyn Wallet is not connected -- add an API key in Settings > Integrations")
    return AcynWalletProvider(config)


employees_router = APIRouter(prefix="/employees", tags=["employees"])
me_router = APIRouter(prefix="/me", tags=["me"])
expense_claims_router = APIRouter(prefix="/expense_claims", tags=["expense-claims"])
payroll_router = APIRouter(prefix="/payroll_runs", tags=["payroll"])


@employees_router.get("", response_model=list[EmployeeOut])
async def list_employees(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(Employee).where(Employee.org_id == _org(principal)).order_by(Employee.name))
    return rows.scalars().all()


@employees_router.post("", response_model=EmployeeOut, status_code=201)
async def create_employee(
    body: EmployeeCreate,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    if body.pay_frequency not in PAY_FREQUENCIES:
        raise HTTPException(422, f"pay_frequency must be one of {PAY_FREQUENCIES}")
    if body.status not in EMPLOYEE_STATUSES:
        raise HTTPException(422, f"status must be one of {EMPLOYEE_STATUSES}")
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


@employees_router.patch("/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeCreate,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    if body.pay_frequency not in PAY_FREQUENCIES:
        raise HTTPException(422, f"pay_frequency must be one of {PAY_FREQUENCIES}")
    if body.status not in EMPLOYEE_STATUSES:
        raise HTTPException(422, f"status must be one of {EMPLOYEE_STATUSES}")
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


@expense_claims_router.get("", response_model=list[ExpenseClaimOut])
async def list_expense_claims(
    mine: bool = False,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    query = select(ExpenseClaim).where(ExpenseClaim.org_id == _org(principal))
    if mine:
        employee = await _resolve_my_employee(session, principal)
        query = query.where(ExpenseClaim.employee_id == employee.id)
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
    claim = ExpenseClaim(
        org_id=_org(principal),
        employee_id=employee.id,
        status="submitted",
        submitted_at=datetime.now(UTC),
        **body.model_dump(),
    )
    session.add(claim)
    await session.commit()
    await session.refresh(claim)
    return claim


async def _get_owned_claim(session: AsyncSession, principal: Principal, claim_id: uuid.UUID) -> ExpenseClaim:
    claim = await session.get(ExpenseClaim, claim_id)
    if claim is None or str(claim.org_id) != principal.org_id:
        raise HTTPException(404, "expense claim not found")
    return claim


@expense_claims_router.patch("/{claim_id}/status", response_model=ExpenseClaimOut)
async def set_expense_claim_status(
    claim_id: uuid.UUID,
    body: ExpenseClaimStatusUpdate,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    """Approve/reject only -- "paid" is reached exclusively through
    POST /{id}/pay, which is the only place that actually calls the
    wallet provider, so a claim can never be marked paid without money
    actually having been queued to move."""
    if body.status not in ("approved", "rejected"):
        raise HTTPException(422, "status must be 'approved' or 'rejected'")
    claim = await _get_owned_claim(session, principal, claim_id)
    if claim.status != "submitted":
        raise HTTPException(400, f"claim is '{claim.status}', not 'submitted'")
    claim.status = body.status
    await session.commit()
    await session.refresh(claim)
    return claim


@expense_claims_router.post("/{claim_id}/pay", response_model=ExpenseClaimOut)
async def pay_expense_claim(
    claim_id: uuid.UUID,
    principal: Principal = Depends(require_role("admin")),
    session: AsyncSession = Depends(get_org_session),
):
    claim = await _get_owned_claim(session, principal, claim_id)
    if claim.status != "approved":
        raise HTTPException(400, f"claim is '{claim.status}', not 'approved'")
    employee = await _get_owned_employee(session, principal, claim.employee_id)
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
                gross_amount_cents=employee.pay_rate_cents,
                to_address=employee.wallet_address,
                network=employee.wallet_network,
                status="pending" if employee.wallet_address else "blocked",
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
                amount=f"{line.gross_amount_cents / 100:.2f}",
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
    failed), the run itself is marked paid."""
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
    if all(l.status in ("blocked", "confirmed", "failed") for l in run.lines):
        run.status = "paid"
        run.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(run, attribute_names=["lines"])
    return PayrollRunOut.from_model(run)


app.include_router(employees_router)
app.include_router(me_router)
app.include_router(expense_claims_router)
app.include_router(payroll_router)
