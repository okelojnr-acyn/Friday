import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_integration_config,
    get_org_session,
    publish_event,
    resource,
)
from friday_common.integrations import StripeProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import (
    INVOICE_STATUSES,
    POS_SHIFT_STATUSES,
    RECURRING_INTERVALS,
    Customer,
    Invoice,
    InvoiceLine,
    Payment,
    PosShift,
)
from .schemas import (
    CustomerCreate,
    CustomerOut,
    InvoiceCreate,
    InvoiceOut,
    InvoiceStatusUpdate,
    PaymentCreate,
    PayWithCardOut,
    PosShiftClose,
    PosShiftOpen,
    PosShiftOut,
)
from .webhooks import external_router
from .webhooks import router as webhooks_router

resource(
    ResourceSpec(
        name="customer",
        app="invoicing",
        label="Customer",
        label_plural="Customers",
        views=("list", "form"),
        search_fields=("name", "company", "email"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("company", "Company", "text"),
            FieldSpec("email", "Email", "email"),
            FieldSpec("created_at", "Added", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="invoice",
        app="invoicing",
        label="Invoice",
        label_plural="Invoices",
        views=("list", "form"),
        search_fields=("number",),
        fields=(
            FieldSpec("number", "Number", "text", form_visible=False),
            FieldSpec(
                "customer_id",
                "Customer",
                "reference",
                reference="invoicing.customer",
                form_visible=False,
            ),
            FieldSpec("status", "Status", "select", options=INVOICE_STATUSES, required=True),
            FieldSpec("total_cents", "Total", "currency", form_visible=False),
            FieldSpec("balance_cents", "Balance", "currency", form_visible=False),
            FieldSpec("source", "Source", "select", options=("manual", "crm", "pos"), form_visible=False),
            # form_visible=False on both: recurring_interval is only ever
            # set at creation time (InvoiceCreateModal's "Repeats" picker)
            # -- the generic form's Save always PATCHes /status (see
            # resourceApi.ts's UPDATE_PATH_OVERRIDES), which has no way to
            # change these, so exposing them as editable here would look
            # editable without actually persisting.
            FieldSpec("recurring_interval", "Repeats", "select", options=RECURRING_INTERVALS, form_visible=False),
            FieldSpec("next_recurrence_at", "Next invoice", "datetime", list_visible=False, form_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="pos_shift",
        app="invoicing",
        label="POS Shift",
        label_plural="POS Shifts",
        views=("list",),
        search_fields=(),
        fields=(
            FieldSpec("opened_at", "Opened", "datetime", required=True),
            FieldSpec("closed_at", "Closed", "datetime"),
            FieldSpec("opening_float_cents", "Opening float", "currency", required=True),
            FieldSpec("closing_count_cents", "Counted", "currency"),
            FieldSpec("expected_cents", "Expected", "currency"),
            FieldSpec("status", "Status", "select", options=POS_SHIFT_STATUSES, required=True),
        ),
    )
)

app = create_app("friday-invoicing")


def _advance(dt: datetime, interval: str) -> datetime:
    """Next occurrence after `dt`. Dependency-free (no dateutil) at the
    cost of clamping a monthly recurrence to day 28 -- a template invoice
    created on the 31st recurs on the 28th every month rather than
    skipping or overflowing into the next month. Good enough for "bill
    roughly monthly"; a deployment that needs exact month-end billing
    should add python-dateutil's relativedelta here instead."""
    if interval == "weekly":
        return dt + timedelta(days=7)
    if interval == "monthly":
        year = dt.year + (dt.month // 12)
        month = dt.month % 12 + 1
        return dt.replace(year=year, month=month, day=min(dt.day, 28))
    if interval == "yearly":
        return dt.replace(year=dt.year + 1)
    raise ValueError(f"unknown recurring interval: {interval!r}")


customers_router = APIRouter(prefix="/customers", tags=["customers"])
invoices_router = APIRouter(prefix="/invoices", tags=["invoices"])
pos_router = APIRouter(prefix="/pos", tags=["pos-sync"])


@customers_router.get("", response_model=list[CustomerOut])
async def list_customers(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Customer).where(Customer.org_id == uuid.UUID(principal.org_id)).order_by(Customer.created_at.desc())
    )
    return rows.scalars().all()


@customers_router.post("", response_model=CustomerOut, status_code=201)
async def create_customer(
    body: CustomerCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    customer = Customer(org_id=uuid.UUID(principal.org_id), created_at=datetime.now(UTC), **body.model_dump())
    session.add(customer)
    await session.commit()
    await session.refresh(customer)
    return customer


async def _get_invoice(session: AsyncSession, principal: Principal, invoice_id: uuid.UUID) -> Invoice:
    inv = await session.get(Invoice, invoice_id)
    if inv is None or str(inv.org_id) != principal.org_id:
        raise HTTPException(404, "invoice not found")
    return inv


@invoices_router.get("", response_model=list[InvoiceOut])
async def list_invoices(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Invoice).where(Invoice.org_id == uuid.UUID(principal.org_id)).order_by(Invoice.created_at.desc())
    )
    return [InvoiceOut.from_model(inv) for inv in rows.scalars().all()]


@invoices_router.post("", response_model=InvoiceOut, status_code=201)
async def create_invoice(
    body: InvoiceCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.recurring_interval not in RECURRING_INTERVALS:
        raise HTTPException(422, f"recurring_interval must be one of {RECURRING_INTERVALS}")
    now = datetime.now(UTC)
    invoice = Invoice(
        org_id=uuid.UUID(principal.org_id),
        customer_id=body.customer_id,
        number=f"INV-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        currency=body.currency,
        source="manual",
        recurring_interval=body.recurring_interval,
        next_recurrence_at=_advance(now, body.recurring_interval) if body.recurring_interval else None,
        created_at=now,
        updated_at=now,
    )
    session.add(invoice)
    await session.flush()
    for line in body.lines:
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=invoice.id,
                description=line.description,
                quantity=line.quantity,
                unit_price_cents=line.unit_price_cents,
            )
        )
    await session.commit()
    await session.refresh(invoice, attribute_names=["lines", "payments"])
    return InvoiceOut.from_model(invoice)


@invoices_router.get("/{invoice_id}", response_model=InvoiceOut)
async def get_invoice(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    inv = await _get_invoice(session, principal, invoice_id)
    return InvoiceOut.from_model(inv)


@invoices_router.patch("/{invoice_id}/status", response_model=InvoiceOut)
async def set_invoice_status(
    invoice_id: uuid.UUID,
    body: InvoiceStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.status not in INVOICE_STATUSES:
        raise HTTPException(422, f"status must be one of {INVOICE_STATUSES}")
    inv = await _get_invoice(session, principal, invoice_id)
    inv.status = body.status
    inv.updated_at = datetime.now(UTC)
    if body.status == "sent" and inv.issued_at is None:
        inv.issued_at = inv.updated_at
    await session.commit()
    await session.refresh(inv, attribute_names=["lines", "payments"])
    return InvoiceOut.from_model(inv)


@invoices_router.post("/{invoice_id}/payments", response_model=InvoiceOut, status_code=201)
async def record_payment(
    invoice_id: uuid.UUID,
    body: PaymentCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    inv = await _get_invoice(session, principal, invoice_id)
    session.add(
        Payment(
            org_id=uuid.UUID(principal.org_id),
            invoice_id=inv.id,
            amount_cents=body.amount_cents,
            method=body.method,
            received_at=datetime.now(UTC),
        )
    )
    await session.flush()
    await session.refresh(inv, attribute_names=["lines", "payments"])

    total = sum(l.total_cents for l in inv.lines)
    paid = sum(p.amount_cents for p in inv.payments)
    if paid >= total and inv.status != "void":
        inv.status = "paid"
        inv.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(inv, attribute_names=["lines", "payments"])
    return InvoiceOut.from_model(inv)


@invoices_router.post("/{invoice_id}/pay-with-card", response_model=PayWithCardOut, status_code=201)
async def pay_with_card(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Creates a Stripe PaymentIntent for the invoice's outstanding
    balance -- the frontend confirms it with Stripe.js using the returned
    client_secret. The actual "mark this invoice paid" side effect
    happens in the webhook below once Stripe reports success, never here
    (this request can be abandoned mid-checkout; the webhook is the only
    thing that moves money server-side)."""
    inv = await _get_invoice(session, principal, invoice_id)
    config = await get_integration_config(principal.org_id, "stripe")
    if not config.get("secret_key"):
        raise HTTPException(400, "Stripe is not connected -- add a secret key in Settings > Integrations")

    total = sum(l.total_cents for l in inv.lines)
    paid = sum(p.amount_cents for p in inv.payments)
    balance = total - paid
    if balance <= 0:
        raise HTTPException(400, "invoice has no outstanding balance")

    intent = await StripeProvider(config).create_payment_intent(
        balance,
        inv.currency,
        {"invoice_id": str(inv.id), "org_id": principal.org_id},
    )
    inv.stripe_payment_intent_id = intent["id"]
    await session.commit()
    return PayWithCardOut(client_secret=intent.get("client_secret"), publishable_key=config.get("publishable_key", ""))


@invoices_router.post("/generate-recurring")
async def generate_recurring_invoices(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Clones every recurring template invoice whose `next_recurrence_at`
    has passed into a fresh draft invoice, then advances the template.
    Meant to be called on a schedule (cron / Task Scheduler hitting this
    route through the kernel with a real org member's token) -- Friday
    deliberately has no built-in scheduler (see ARCHITECTURE.md's "what
    we explicitly did not build"), so this is the one piece a deployment
    wires up itself."""
    now = datetime.now(UTC)
    due = await session.execute(
        select(Invoice).where(
            Invoice.org_id == uuid.UUID(principal.org_id),
            Invoice.recurring_interval != "",
            Invoice.next_recurrence_at <= now,
        )
    )
    created = []
    for template in due.scalars().all():
        await session.refresh(template, attribute_names=["lines"])
        new_invoice = Invoice(
            org_id=template.org_id,
            customer_id=template.customer_id,
            number=f"INV-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
            status="draft",
            currency=template.currency,
            source="manual",
            source_ref=str(template.id),
            created_at=now,
            updated_at=now,
        )
        session.add(new_invoice)
        await session.flush()
        for line in template.lines:
            session.add(
                InvoiceLine(
                    org_id=template.org_id,
                    invoice_id=new_invoice.id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price_cents=line.unit_price_cents,
                )
            )
        template.next_recurrence_at = _advance(template.next_recurrence_at, template.recurring_interval)
        created.append(new_invoice)

    await session.commit()
    for inv in created:
        await session.refresh(inv, attribute_names=["lines", "payments"])
    return [InvoiceOut.from_model(inv) for inv in created]


@pos_router.post("/sales", status_code=201)
async def record_pos_sale(
    body: dict,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Where the Rust POS engine's offline sync queue lands once a device
    is back online. A POS sale becomes an already-paid invoice with
    source='pos' -- same ledger, no separate "sales" table to reconcile
    against invoicing later."""
    now = datetime.now(UTC)
    lines_in = body.get("lines", [])
    if not lines_in:
        raise HTTPException(422, "sale must have at least one line")

    invoice = Invoice(
        org_id=uuid.UUID(principal.org_id),
        number=f"POS-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        status="paid",
        currency=body.get("currency", "USD"),
        source="pos",
        source_ref=body.get("client_sale_id"),
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(invoice)
    await session.flush()

    total_cents = 0
    for line in lines_in:
        qty = line.get("quantity", 1)
        unit_price = line.get("unit_price_cents", 0)
        total_cents += int(qty * unit_price)
        product_id = line.get("product_id")
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=invoice.id,
                description=line.get("description", "Item"),
                quantity=qty,
                unit_price_cents=unit_price,
                product_id=uuid.UUID(product_id) if product_id else None,
            )
        )

    # pos-engine's Cart.total_cents() (what the register actually charged,
    # body["amount_cents"]) includes tax; the line items above don't carry
    # a tax line of their own. Without reconciling the two, total_cents
    # (sum of lines) undercounts what was paid and the invoice shows a
    # negative balance on every taxed sale. Record the difference as its
    # own line so the invoice ledger and the amount collected always agree.
    charged_cents = body.get("amount_cents", total_cents)
    tax_cents = charged_cents - total_cents
    if tax_cents > 0:
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=invoice.id,
                description="Tax",
                quantity=1,
                unit_price_cents=tax_cents,
            )
        )
        total_cents = charged_cents

    # Split tender (see pos-engine's Sale.payments): one Payment row per
    # tender instead of one for the whole charged_cents. Falls back to
    # the ordinary single-Payment path when the sale has no payments
    # array at all -- every sale from an older pos-engine build, or any
    # single-tender sale, takes this branch exactly as before.
    payments_in = body.get("payments") or []
    if payments_in:
        payments_total = sum(int(p.get("amount_cents", 0)) for p in payments_in)
        if payments_total != charged_cents:
            raise HTTPException(
                422, f"split payments total {payments_total} does not match amount_cents {charged_cents}"
            )
        for p in payments_in:
            session.add(
                Payment(
                    org_id=uuid.UUID(principal.org_id),
                    invoice_id=invoice.id,
                    amount_cents=int(p["amount_cents"]),
                    method=p.get("method", "other"),
                    received_at=now,
                )
            )
    else:
        session.add(
            Payment(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=invoice.id,
                amount_cents=charged_cents,
                method=body.get("method", "pos"),
                received_at=now,
            )
        )
    await session.commit()
    await session.refresh(invoice, attribute_names=["lines", "payments"])

    # Lets Inventory auto-decrement stock for any line rung up from the
    # product catalog (product_id set client-side by the POS register --
    # see web/src/apps/pos/PosPage.tsx). Freeform/ad-hoc lines have no
    # product_id and are skipped on the subscriber side.
    await publish_event(
        "invoicing.pos_sale.recorded",
        principal.org_id,
        {
            "invoice_number": invoice.number,
            "lines": [
                {
                    "product_id": line.get("product_id"),
                    "quantity": line.get("quantity", 1),
                }
                for line in lines_in
                if line.get("product_id")
            ],
        },
    )

    return InvoiceOut.from_model(invoice)


async def _get_pos_sale(session: AsyncSession, principal: Principal, number: str) -> Invoice:
    rows = await session.execute(
        select(Invoice).where(
            Invoice.org_id == uuid.UUID(principal.org_id), Invoice.number == number, Invoice.source == "pos"
        )
    )
    inv = rows.scalars().first()
    if inv is None:
        raise HTTPException(404, "pos sale not found")
    return inv


@pos_router.get("/sales/{number}", response_model=InvoiceOut)
async def get_pos_sale(
    number: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Looks up a past sale by receipt number -- what the POS register's
    returns screen calls before offering to refund it."""
    inv = await _get_pos_sale(session, principal, number)
    return InvoiceOut.from_model(inv)


@pos_router.post("/sales/{number}/return", response_model=InvoiceOut, status_code=201)
async def return_pos_sale(
    number: str,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Refunds a past POS sale in full: a new invoice mirroring every
    line with a negated quantity, a matching negative Payment, and the
    original marked void -- same ledger, no separate refunds table (see
    ARCHITECTURE.md's "one ledger to reconcile, not two" for why POS
    sales work this way in the first place). Publishing the *same*
    invoicing.pos_sale.recorded event shape with negative quantities
    makes Inventory's existing pos_sale_recorded webhook restock
    automatically -- zero Inventory code needed for returns."""
    original = await _get_pos_sale(session, principal, number)
    if original.status == "void":
        raise HTTPException(400, "sale is already void")
    await session.refresh(original, attribute_names=["lines", "payments"])

    now = datetime.now(UTC)
    refund = Invoice(
        org_id=uuid.UUID(principal.org_id),
        number=f"RET-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        status="paid",
        currency=original.currency,
        source="pos",
        source_ref=original.number,
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(refund)
    await session.flush()

    refund_total_cents = 0
    for line in original.lines:
        refund_total_cents += -line.total_cents
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=refund.id,
                description=f"Return: {line.description}",
                quantity=-line.quantity,
                unit_price_cents=line.unit_price_cents,
                product_id=line.product_id,
            )
        )

    session.add(
        Payment(
            org_id=uuid.UUID(principal.org_id),
            invoice_id=refund.id,
            amount_cents=refund_total_cents,
            method="refund",
            received_at=now,
        )
    )
    original.status = "void"
    original.updated_at = now

    await session.commit()
    await session.refresh(refund, attribute_names=["lines", "payments"])

    await publish_event(
        "invoicing.pos_sale.recorded",
        principal.org_id,
        {
            "invoice_number": refund.number,
            "lines": [
                {"product_id": str(line.product_id), "quantity": float(line.quantity)}
                for line in refund.lines
                if line.product_id
            ],
        },
    )

    return InvoiceOut.from_model(refund)


@pos_router.get("/shifts", response_model=list[PosShiftOut])
async def list_pos_shifts(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(PosShift).where(PosShift.org_id == uuid.UUID(principal.org_id)).order_by(PosShift.opened_at.desc())
    )
    return rows.scalars().all()


@pos_router.get("/shifts/current", response_model=PosShiftOut)
async def get_current_pos_shift(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(PosShift).where(PosShift.org_id == uuid.UUID(principal.org_id), PosShift.status == "open")
    )
    shift = rows.scalars().first()
    if shift is None:
        raise HTTPException(404, "no open shift")
    return shift


@pos_router.post("/shifts/open", response_model=PosShiftOut, status_code=201)
async def open_pos_shift(
    body: PosShiftOpen,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The DB-level partial unique index (idx_pos_shifts_one_open_per_org,
    see 0006_pos_shifts.sql) is the real guard against two concurrent
    opens racing each other -- this check is just a clean error message
    for the ordinary case where there's already a visibly open shift."""
    existing = await session.execute(
        select(PosShift).where(PosShift.org_id == uuid.UUID(principal.org_id), PosShift.status == "open")
    )
    if existing.scalars().first() is not None:
        raise HTTPException(400, "a shift is already open -- close it before opening a new one")

    shift = PosShift(
        org_id=uuid.UUID(principal.org_id),
        opened_at=datetime.now(UTC),
        opening_float_cents=body.opening_float_cents,
        status="open",
    )
    session.add(shift)
    await session.commit()
    await session.refresh(shift)
    return shift


@pos_router.post("/shifts/{shift_id}/close", response_model=PosShiftOut)
async def close_pos_shift(
    shift_id: uuid.UUID,
    body: PosShiftClose,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Expected cash = opening float + cash payments received during the
    shift's window. Known gap: a cash refund is always recorded with
    method="refund" (see return_pos_sale), never "cash" specifically --
    there's no payment-method tracking on a refund today -- so a cash
    refund during this shift won't reduce the expected count. Documented
    here rather than silently wrong."""
    shift = await session.get(PosShift, shift_id)
    if shift is None or str(shift.org_id) != principal.org_id:
        raise HTTPException(404, "shift not found")
    if shift.status != "open":
        raise HTTPException(400, "shift is already closed")

    now = datetime.now(UTC)
    cash_rows = await session.execute(
        select(Payment).where(
            Payment.org_id == uuid.UUID(principal.org_id),
            Payment.method == "cash",
            Payment.received_at >= shift.opened_at,
            Payment.received_at <= now,
        )
    )
    cash_total = sum(p.amount_cents for p in cash_rows.scalars().all())

    shift.closed_at = now
    shift.closing_count_cents = body.closing_count_cents
    shift.expected_cents = shift.opening_float_cents + cash_total
    shift.status = "closed"
    await session.commit()
    await session.refresh(shift)
    return shift


app.include_router(customers_router)
app.include_router(invoices_router)
app.include_router(pos_router)
app.include_router(webhooks_router)
app.include_router(external_router)
