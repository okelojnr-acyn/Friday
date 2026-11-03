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

from .events import invoice_lines_payload, publish_invoice_paid
from .models import INVOICE_STATUSES, RECURRING_INTERVALS, Customer, Invoice, InvoiceLine, Payment
from .schemas import (
    CustomerBulkCreate,
    CustomerCreate,
    CustomerOut,
    InvoiceCreate,
    InvoiceOut,
    InvoiceStatusUpdate,
    PaymentCreate,
    PayWithCardOut,
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
            FieldSpec("payment_terms_days", "Payment terms (days)", "number"),
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
            FieldSpec("due_at", "Due", "date", form_visible=False),
            FieldSpec("total_cents", "Total", "currency", form_visible=False),
            FieldSpec("balance_cents", "Balance", "currency", form_visible=False),
            FieldSpec(
                "source", "Source", "select", options=("manual", "crm", "pos", "credit_note"), form_visible=False
            ),
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


@customers_router.post("/bulk", response_model=list[CustomerOut], status_code=201)
async def bulk_create_customers(
    body: CustomerBulkCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Mirrors apps/inventory/app/main.py's bulk_create_products -- lets a
    caller load an existing customer list in one request instead of one
    round trip per row."""
    now = datetime.now(UTC)
    created = [Customer(org_id=uuid.UUID(principal.org_id), created_at=now, **item.model_dump()) for item in body.customers]
    session.add_all(created)
    await session.commit()
    for customer in created:
        await session.refresh(customer)
    return created


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
    due_at = None
    if body.customer_id is not None:
        customer = await session.get(Customer, body.customer_id)
        if customer is not None and str(customer.org_id) == principal.org_id:
            due_at = now + timedelta(days=customer.payment_terms_days)
    invoice = Invoice(
        org_id=uuid.UUID(principal.org_id),
        customer_id=body.customer_id,
        number=f"INV-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        currency=body.currency,
        source="manual",
        due_at=due_at,
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
                tax_rate_bp=line.tax_rate_bp,
                discount_bp=line.discount_bp,
                unit_cost_cents=line.unit_cost_cents,
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
    newly_paid = paid >= total and inv.status not in ("paid", "void")
    if paid >= total and inv.status != "void":
        inv.status = "paid"
        inv.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(inv, attribute_names=["lines", "payments"])
    if newly_paid:
        await publish_invoice_paid(principal.org_id, inv, paid, invoice_lines_payload(inv))
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
        discount_bp = line.get("discount_bp", 0)
        product_id = line.get("product_id")
        invoice_line = InvoiceLine(
            org_id=uuid.UUID(principal.org_id),
            invoice_id=invoice.id,
            description=line.get("description", "Item"),
            quantity=qty,
            unit_price_cents=unit_price,
            discount_bp=discount_bp,
            unit_cost_cents=line.get("unit_cost_cents"),
            product_id=uuid.UUID(product_id) if product_id else None,
        )
        session.add(invoice_line)
        total_cents += invoice_line.total_cents

    # pos-engine's Cart.total_cents() (what the register actually charged,
    # body["amount_cents"]) includes tax and any per-line discounts have
    # already been applied above (InvoiceLine.total_cents accounts for
    # discount_bp) -- but a POS-side rounding difference or a flat tax
    # rate still needs reconciling against the line total. The sign tells
    # us which: positive means tax was charged beyond the lines' total,
    # negative means the lines (post-discount) still overstate what was
    # actually collected. Recording it as its own line keeps the invoice
    # ledger and the amount collected in exact agreement either way.
    charged_cents = body.get("amount_cents", total_cents)
    adjustment_cents = charged_cents - total_cents
    if adjustment_cents != 0:
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=invoice.id,
                description="Tax" if adjustment_cents > 0 else "Discount",
                quantity=1,
                unit_price_cents=adjustment_cents,
            )
        )
        total_cents = charged_cents

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
    # product_id and are skipped on the subscriber side. unit_cost_cents
    # rides along unused by Inventory's own subscriber, but is what a
    # future Accounting COGS webhook on this same event would post
    # against -- see record_pos_sale's own line construction above for
    # where this value comes from.
    await publish_event(
        "invoicing.pos_sale.recorded",
        principal.org_id,
        {
            "invoice_number": invoice.number,
            "lines": [
                {
                    "product_id": line.get("product_id"),
                    "quantity": line.get("quantity", 1),
                    "unit_cost_cents": line.get("unit_cost_cents"),
                }
                for line in lines_in
                if line.get("product_id")
            ],
        },
    )
    # A POS sale is created already-paid, so this is always a "newly
    # paid" transition -- no status check needed, unlike record_payment.
    await publish_invoice_paid(principal.org_id, invoice, charged_cents, invoice_lines_payload(invoice))

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
                discount_bp=line.discount_bp,
                unit_cost_cents=line.unit_cost_cents,
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
                {
                    "product_id": str(line.product_id),
                    "quantity": float(line.quantity),
                    "unit_cost_cents": line.unit_cost_cents,
                }
                for line in refund.lines
                if line.product_id
            ],
        },
    )
    # Negative paid_amount_cents -- Accounting's invoice-paid webhook
    # mirrors the debit/credit sides for a negative amount so the ledger
    # itself never carries a negative entry.
    await publish_invoice_paid(principal.org_id, refund, refund_total_cents, invoice_lines_payload(refund))

    return InvoiceOut.from_model(refund)


@invoices_router.post("/{invoice_id}/credit-note", response_model=InvoiceOut, status_code=201)
async def create_credit_note(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """Credit notes as a first-class concept for manual invoices -- same
    negated-lines pattern return_pos_sale already established for POS
    refunds, applied here instead of editing the original invoice (which
    stays exactly as issued; a credit note is a new document, same as
    every real-world accounting system treats it). Unlike a POS return,
    the original isn't voided -- a credit note can be partial, or issued
    against an invoice that was never actually paid in full."""
    original = await _get_invoice(session, principal, invoice_id)
    await session.refresh(original, attribute_names=["lines", "payments"])

    now = datetime.now(UTC)
    note = Invoice(
        org_id=uuid.UUID(principal.org_id),
        customer_id=original.customer_id,
        number=f"CN-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="paid",
        currency=original.currency,
        source="credit_note",
        source_ref=original.number,
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(note)
    await session.flush()

    note_total_cents = 0
    for line in original.lines:
        note_total_cents += -(line.total_cents + line.tax_cents)
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=note.id,
                description=f"Credit: {line.description}",
                quantity=-line.quantity,
                unit_price_cents=line.unit_price_cents,
                tax_rate_bp=line.tax_rate_bp,
                product_id=line.product_id,
            )
        )

    session.add(
        Payment(
            org_id=uuid.UUID(principal.org_id),
            invoice_id=note.id,
            amount_cents=note_total_cents,
            method="refund",
            received_at=now,
        )
    )
    await session.commit()
    await session.refresh(note, attribute_names=["lines", "payments"])

    await publish_invoice_paid(principal.org_id, note, note_total_cents, invoice_lines_payload(note))

    return InvoiceOut.from_model(note)


app.include_router(customers_router)
app.include_router(invoices_router)
app.include_router(pos_router)
app.include_router(webhooks_router)
app.include_router(external_router)
