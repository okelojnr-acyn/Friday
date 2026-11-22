import logging
import uuid
from types import SimpleNamespace
from decimal import ROUND_HALF_UP, Decimal
from datetime import UTC, date, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from friday_common.importer import ImportField, ImportTarget, import_router
from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_integration_config,
    get_org_session,
    get_settings,
    resource,
)
from friday_common.integrations import PesapalProvider, ResendProvider, StripeProvider
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .credit import customer_by_name, rebook_ref
from .credit import router as credit_router
from .events import invoice_lines_payload, publish_invoice_paid, publish_pos_sale_recorded
from .models import (
    INVOICE_STATUSES,
    POS_SHIFT_STATUSES,
    QUOTE_MANUAL_STATUSES,
    QUOTE_STATUSES,
    RECURRING_INTERVALS,
    Customer,
    Invoice,
    InvoiceLine,
    Payment,
)
from .schemas import (
    ArAgingCurrencyTotals,
    ArAgingCustomerRow,
    ArAgingOut,
    CustomerBulkCreate,
    CustomerCreate,
    CustomerOut,
    InvoiceCreate,
    InvoiceOut,
    InvoiceStatusUpdate,
    PaymentCreate,
    PayWithCardOut,
    PayWithPesapalOut,
    PaystackCheckoutOut,
    PosSaleStatusOut,
    QuoteCreate,
    QuoteStatusUpdate,
)
from friday_common.access import APPROVAL_HEADER, Scope, check_approval, require, scope_for
from friday_common.etims import normalize_pin
from friday_common.etims.kernel import get_etims_config

from .etims_routes import router as etims_router
from .paystack_pay import manual_tenders, refund_share
from .paystack_pay import router as paystack_router
from .paystack_pay import settle as settle_paystack
from .paystack_pay import start_checkout as start_paystack_checkout
from .paystack_pay import start_mpesa_prompt
from .registers import router as registers_router
from .registers import at_place, shift_for_sale, till_location
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

resource(
    ResourceSpec(
        name="quote",
        app="invoicing",
        label="Quote",
        label_plural="Quotes",
        views=("list", "form"),
        search_fields=("number",),
        fields=(
            FieldSpec("number", "Number", "text", form_visible=False),
            FieldSpec(
                "customer_id", "Customer", "reference", reference="invoicing.customer", form_visible=False
            ),
            # Editable via PATCH /quotes/{id}/status (resourceApi.ts
            # UPDATE_PATH_OVERRIDES); "accepted" is only ever set by
            # POST /quotes/{id}/convert.
            FieldSpec("status", "Status", "select", options=QUOTE_STATUSES, required=True),
            FieldSpec("valid_until", "Valid until", "date", form_visible=False),
            FieldSpec("total_cents", "Total", "currency", form_visible=False),
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
logger = logging.getLogger("friday.invoicing")


async def _email_invoice(org_id: str, inv: Invoice, session: AsyncSession) -> None:
    """Best-effort: an org that hasn't connected Resend (the common case
    today), or whose customer has no email on file, just gets no email --
    same posture as crm/app/main.py's _notify_slack. A missing/
    misconfigured provider must never fail the status update that
    triggered this."""
    if inv.customer_id is None:
        return
    customer = await session.get(Customer, inv.customer_id)
    if customer is None or not customer.email:
        return
    config = await get_integration_config(org_id, "resend")
    if not config.get("api_key"):
        return
    total = sum(line.total_cents + line.tax_cents for line in inv.lines)
    html = (
        f"<p>Hi {customer.name},</p>"
        f"<p>Invoice <strong>{inv.number}</strong> for "
        f"<strong>{total / 100:.2f} {inv.currency}</strong> is ready."
    )
    if inv.due_at is not None:
        html += f"<p>Due {inv.due_at:%Y-%m-%d}.</p>"
    try:
        await ResendProvider(config).send(customer.email, f"Invoice {inv.number}", html)
    except Exception as exc:  # noqa: BLE001 -- see docstring, this must never propagate
        logger.warning("resend invoice email failed: %s", exc)


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
    _scope: Scope = Depends(require("customers.read")),
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
    _scope: Scope = Depends(require("customers.write")),
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
    _scope: Scope = Depends(require("customers.write")),
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


def _doc_allowed(scope: Scope | None, inv: Invoice) -> bool:
    """Whether `scope` covers this document: everywhere; at one of their
    locations; or (team/own) rung up by them or their team."""
    if scope is None:
        return False
    if scope.everywhere:
        return True
    if scope.kind == "loc":
        return inv.location_id is not None and scope.allows_location(str(inv.location_id))
    return scope.allows_person(inv.cashier_user_id)


async def _get_invoice(
    session: AsyncSession,
    principal: Principal,
    invoice_id: uuid.UUID,
    kind: str = "invoice",
    scope: Scope | None = None,
) -> Invoice:
    """`kind` keeps /invoices/{id} and /quotes/{id} from acting on each
    other's documents (same table, see 0009_quotes.sql) -- e.g. marking a
    quote "paid" through the invoice status endpoint. With `scope`, a
    document outside it reads as not found."""
    inv = await session.get(Invoice, invoice_id)
    if inv is None or str(inv.org_id) != principal.org_id or inv.kind != kind:
        raise HTTPException(404, f"{kind} not found")
    if scope is not None and not _doc_allowed(scope, inv):
        raise HTTPException(404, f"{kind} not found")
    return inv


def _in_scope(q, scope: Scope):
    """Narrows an Invoice query to `scope`."""
    if scope.everywhere:
        return q
    if scope.kind == "loc":
        return q.where(Invoice.location_id.in_([uuid.UUID(x) for x in scope.locs if x != "*"]))
    return scope.filter_people(q, Invoice.cashier_user_id)


@invoices_router.get("", response_model=list[InvoiceOut])
async def list_invoices(
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.read")),
    session: AsyncSession = Depends(get_org_session),
):
    q = select(Invoice).where(Invoice.org_id == uuid.UUID(principal.org_id), Invoice.kind == "invoice")
    rows = await session.execute(_in_scope(q, scope).order_by(Invoice.created_at.desc()))
    return [InvoiceOut.from_model(inv) for inv in rows.scalars().all()]


@invoices_router.post("", response_model=InvoiceOut, status_code=201)
async def create_invoice(
    body: InvoiceCreate,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("invoices.write")),
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
    if not (_doc_allowed(scope_for(principal, "invoices.read"), inv) or _doc_allowed(scope_for(principal, "sales.read"), inv)):
        raise HTTPException(404, "invoice not found")
    return InvoiceOut.from_model(inv)


@invoices_router.patch("/{invoice_id}/status", response_model=InvoiceOut)
async def set_invoice_status(
    invoice_id: uuid.UUID,
    body: InvoiceStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.write")),
    session: AsyncSession = Depends(get_org_session),
):
    if body.status not in INVOICE_STATUSES:
        raise HTTPException(422, f"status must be one of {INVOICE_STATUSES}")
    inv = await _get_invoice(session, principal, invoice_id, scope=scope)
    inv.status = body.status
    inv.updated_at = datetime.now(UTC)
    newly_sent = body.status == "sent" and inv.issued_at is None
    if newly_sent:
        inv.issued_at = inv.updated_at
    await session.commit()
    await session.refresh(inv, attribute_names=["lines", "payments"])
    if newly_sent:
        await _email_invoice(principal.org_id, inv, session)
    return InvoiceOut.from_model(inv)


@invoices_router.post("/{invoice_id}/payments", response_model=InvoiceOut, status_code=201)
async def record_payment(
    invoice_id: uuid.UUID,
    body: PaymentCreate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.write")),
    session: AsyncSession = Depends(get_org_session),
):
    inv = await _get_invoice(session, principal, invoice_id, scope=scope)
    if inv.kind != "invoice":
        raise HTTPException(400, "payments can only be recorded against an invoice, not a quote")
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

    total = inv.grand_total_cents  # incl. tax -- see Invoice.grand_total_cents
    paid = inv.paid_cents
    newly_paid = paid >= total and inv.status not in ("paid", "void")
    if paid >= total and inv.status != "void":
        inv.status = "paid"
        inv.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(inv, attribute_names=["lines", "payments"])
    if newly_paid:
        await publish_invoice_paid(
            principal.org_id, inv, paid, invoice_lines_payload(inv), posting_ref=rebook_ref(inv, uuid.uuid4().hex)
        )
    return InvoiceOut.from_model(inv)


@invoices_router.post("/{invoice_id}/pay-with-card", response_model=PayWithCardOut, status_code=201)
async def pay_with_card(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Creates a Stripe PaymentIntent for the invoice's outstanding
    balance -- the frontend confirms it with Stripe.js using the returned
    client_secret. The actual "mark this invoice paid" side effect
    happens in the webhook below once Stripe reports success, never here
    (this request can be abandoned mid-checkout; the webhook is the only
    thing that moves money server-side)."""
    inv = await _get_invoice(session, principal, invoice_id, scope=scope)
    config = await get_integration_config(principal.org_id, "stripe")
    if not config.get("secret_key"):
        raise HTTPException(400, "Stripe is not connected -- add a secret key in Settings > Integrations")

    if inv.kind != "invoice":
        raise HTTPException(400, "a quote can't be paid -- convert it to an invoice first")
    balance = inv.balance_cents  # incl. tax -- see Invoice.grand_total_cents
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


@invoices_router.post("/{invoice_id}/paystack-link", response_model=PaystackCheckoutOut, status_code=201)
async def paystack_pay_link(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """A Paystack page for the invoice's outstanding balance, to send to
    the customer (card, M-Pesa or bank). Paid only once Paystack's verify
    says so (paystack_pay.settle); a new link replaces the last one, and
    a payment on either still counts once."""
    inv = await _get_invoice(session, principal, invoice_id, scope=scope)
    if inv.kind != "invoice":
        raise HTTPException(400, "a quote can't be paid -- convert it to an invoice first")
    if inv.status in ("void", "pending"):
        raise HTTPException(400, f"a {inv.status} invoice can't take a payment link")
    balance = inv.balance_cents
    if balance <= 0:
        raise HTTPException(400, "invoice has no outstanding balance")
    email = ""
    if inv.customer_id:
        customer = await session.get(Customer, inv.customer_id)
        email = customer.email if customer else ""
    redirect_url = await start_paystack_checkout(
        principal.org_id, inv, balance, email, principal.email or "", f"Invoice {inv.number}"
    )
    await session.commit()
    return PaystackCheckoutOut(invoice_id=inv.id, redirect_url=redirect_url)


@invoices_router.post("/generate-recurring")
async def generate_recurring_invoices(
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("invoices.write")),
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


def _fill_vat(invoice_line: "InvoiceLine", cfg: dict) -> None:
    """VAT inside a line's price, for a sale that didn't work it out itself
    (Guss sends shelf prices; the till computes VAT on the device). Uses
    the line's tax type, else the business default, and the business's
    rates; nothing for a business that isn't VAT-registered."""
    code = invoice_line.tax_code or cfg.get("default_code") or "B"
    invoice_line.tax_code = code
    if cfg.get("vat_registered") is False:
        return
    rates = {r["code"]: int(r["rate_bp"]) for r in cfg.get("rates") or []}
    rate = rates.get(code, 1600 if code == "B" else 0)
    total = invoice_line.total_cents
    invoice_line.vat_cents = int((Decimal(total) * rate / (10_000 + rate)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


async def _apply_pos_sale_lines(
    session: AsyncSession,
    principal: Principal,
    invoice: Invoice,
    lines_in: list[dict],
    body: dict,
    vat_cfg: dict | None = None,
) -> int:
    """Builds InvoiceLine rows for a POS sale and reconciles pos-engine's
    charged total against the lines' own total. Shared by record_pos_sale
    (cash/card, already-paid) and pay_with_pesapal (status="pending" until
    the gateway confirms) -- both build identical line/tax-adjustment data
    from the same sale payload shape, only what happens to Payment rows
    afterward differs."""
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
            **_etims_line_fields(line),
        )
        if vat_cfg is not None and "vat_cents" not in line:
            _fill_vat(invoice_line, vat_cfg)
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
                is_adjustment=True,
            )
        )
    # eTIMS: the buyer's KRA PIN (a business buying) and how the till
    # priced the sale.
    invoice.buyer_pin = normalize_pin(body.get("buyer_pin"))[:20]
    invoice.buyer_name = str(body.get("buyer_name") or "").strip()[:120]
    if isinstance(body.get("prices_include_tax"), bool):
        invoice.prices_include_tax = body["prices_include_tax"]
    return charged_cents


def _etims_line_fields(line: dict) -> dict:
    """The tax type, VAT and eTIMS item details the till put on a line."""

    def text_field(key: str, limit: int) -> str:
        return str(line.get(key) or "").strip()[:limit]

    vat = line.get("vat_cents")
    factor = line.get("uom_factor")
    efactor = line.get("etims_qty_factor")
    return {
        "uom_name": text_field("uom", 12),
        "uom_factor": Decimal(str(factor)) if isinstance(factor, (int, float, str)) and str(factor) else None,
        "etims_qty_factor": Decimal(str(efactor)) if isinstance(efactor, (int, float)) and efactor > 0 else Decimal(1),
        "tax_code": text_field("tax_code", 4).upper(),
        "vat_cents": int(vat) if isinstance(vat, (int, float)) else 0,
        "item_code": text_field("etims_item_code", 20),
        "item_class": text_field("etims_item_class", 10),
        "quantity_unit": text_field("etims_quantity_unit", 5),
        "packaging_unit": text_field("etims_packaging_unit", 5),
    }


def _sale_time(body: dict) -> datetime:
    """When the sale happened: the till's created_at_ms if it's plausible
    (not in the future, not older than 30 days), else now."""
    now = datetime.now(UTC)
    ms = body.get("created_at_ms")
    if isinstance(ms, (int, float)):
        t = datetime.fromtimestamp(ms / 1000, UTC)
        if now - timedelta(days=30) <= t <= now + timedelta(minutes=5):
            return min(t, now)
    return now


async def _pos_sale_by_client_id(session: AsyncSession, principal: Principal, client_sale_id: str) -> Invoice | None:
    rows = await session.execute(
        select(Invoice).where(
            Invoice.org_id == uuid.UUID(principal.org_id),
            Invoice.source == "pos",
            Invoice.number.like("POS-%"),
            Invoice.source_ref == client_sale_id,
        )
    )
    inv = rows.scalars().first()
    if inv is not None:
        await session.refresh(inv, attribute_names=["lines", "payments"])
    return inv


@pos_router.post("/sales", status_code=201)
async def record_pos_sale(
    body: dict,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    """Where the Rust POS engine's offline sync queue lands once a device
    is back online. A POS sale becomes an already-paid invoice with
    source='pos' -- same ledger, no separate "sales" table to reconcile
    against invoicing later.

    Recorded once per client_sale_id: a till resends a sale whose reply
    it never got, and the second send returns the first invoice
    (idx_invoices_pos_sale_once backs this up under a race). The sale's
    own time (created_at_ms) dates it, not the moment it synced."""
    lines_in = body.get("lines", [])
    if not lines_in:
        raise HTTPException(422, "sale must have at least one line")
    client_sale_id = body.get("client_sale_id")
    if client_sale_id:
        existing = await _pos_sale_by_client_id(session, principal, str(client_sale_id))
        if existing is not None:
            return InvoiceOut.from_model(existing)
    now = _sale_time(body)
    # A sale made through Guss never joins a till's shift (its cash isn't
    # in that drawer), and its VAT is worked out here from shelf prices.
    channel = "guss" if body.get("channel") == "guss" else "till"
    # Sold on credit ("sold to John on credit"): the customer owes it, no
    # money moves now. The sale stays unpaid against them until they pay
    # (pos/debts/payments); stock still leaves now.
    on_credit = bool(body.get("on_credit"))
    customer = None
    if on_credit:
        if body.get("payments"):
            raise HTTPException(422, "a credit sale has no payments; record them when the customer pays")
        customer = await customer_by_name(session, principal, str(body.get("customer_name") or ""), create=True)
        if customer is None:
            raise HTTPException(422, "a credit sale needs the customer's name")
    shift_id = None if channel == "guss" else await shift_for_sale(session, principal, body.get("shift_id"))
    # Where it was sold: the till's location (a Guss sale has no till).
    location_id = await till_location(session, shift_id)
    at_place(scope, location_id)
    vat_cfg = None
    if channel == "guss" and any("vat_cents" not in line for line in lines_in):
        vat_cfg = await get_etims_config(principal.org_id)

    invoice = Invoice(
        org_id=uuid.UUID(principal.org_id),
        channel=channel,
        prices_include_tax=True if channel == "guss" else None,
        number=f"POS-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        status="sent" if on_credit else "paid",
        customer_id=customer.id if customer else None,
        due_at=now + timedelta(days=customer.payment_terms_days) if customer else None,
        currency=body.get("currency", "USD"),
        source="pos",
        source_ref=client_sale_id,
        cashier_user_id=principal.user_id,
        cashier_email=principal.email,
        pos_shift_id=shift_id,
        location_id=location_id,
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(invoice)
    await session.flush()

    charged_cents = await _apply_pos_sale_lines(session, principal, invoice, lines_in, body, vat_cfg)

    # Split tender (see pos-engine's Sale.payments): one Payment row per
    # tender instead of one for the whole charged_cents. Falls back to
    # the ordinary single-Payment path when the sale has no payments
    # array at all -- every sale from an older pos-engine build, or any
    # single-tender sale, takes this branch exactly as before.
    payments_in = body.get("payments") or []
    if on_credit:
        pass  # nothing paid yet
    elif payments_in:
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
    try:
        await session.commit()
    except IntegrityError:
        # The same sale arrived twice at once; the other request saved it.
        await session.rollback()
        existing = await _pos_sale_by_client_id(session, principal, str(client_sale_id))
        if existing is None:
            raise
        return InvoiceOut.from_model(existing)
    await session.refresh(invoice, attribute_names=["lines", "payments"])

    # Lets Inventory auto-decrement stock for any line rung up from the
    # product catalog, and Minions attribute the sale to an employee (see
    # publish_pos_sale_recorded's own doc comment).
    await publish_pos_sale_recorded(principal.org_id, invoice, charged_cents)
    # A POS sale is created already-paid, so this is always a "newly
    # paid" transition -- no status check needed, unlike record_payment.
    # A credit sale reaches the books when it's paid, like an invoice.
    if not on_credit:
        await publish_invoice_paid(principal.org_id, invoice, charged_cents, invoice_lines_payload(invoice))

    return InvoiceOut.from_model(invoice)


@pos_router.post("/sales/pay-with-pesapal", response_model=PayWithPesapalOut, status_code=201)
async def pay_with_pesapal(
    body: dict,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    """Starts a real Pesapal checkout for a POS sale -- unlike
    record_pos_sale (cash/card-today, always already-paid), this creates
    the invoice with status="pending" and no Payment row yet: no money
    has moved, and won't until pesapal_webhook (webhooks.py) confirms it
    via Pesapal's own GetTransactionStatus, the only place that marks this
    paid. Deliberately online-only -- there's no offline-queue path for
    this the way cash/card have through pos-engine's OfflineQueue; the
    frontend can't optimistically clear the cart the way it does for
    those."""
    now = datetime.now(UTC)
    lines_in = body.get("lines", [])
    if not lines_in:
        raise HTTPException(422, "sale must have at least one line")

    config = await get_integration_config(principal.org_id, "pesapal")
    if not config.get("consumer_key"):
        raise HTTPException(400, "Pesapal is not connected -- add a consumer key/secret in Settings > Integrations")

    settings = get_settings()
    if not settings.app_public_url:
        raise HTTPException(
            500, "APP_PUBLIC_URL is not configured for this service -- Pesapal needs a real callback URL"
        )

    invoice = Invoice(
        org_id=uuid.UUID(principal.org_id),
        number=f"POS-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        status="pending",
        currency=body.get("currency", "USD"),
        source="pos",
        source_ref=body.get("client_sale_id"),
        cashier_user_id=principal.user_id,
        cashier_email=principal.email,
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(invoice)
    await session.flush()

    charged_cents = await _apply_pos_sale_lines(session, principal, invoice, lines_in, body)
    await session.commit()

    # org_id rides along in the merchant_reference, not just invoice_id,
    # for the same reason Stripe's PaymentIntent metadata carries org_id:
    # pesapal_webhook has no Friday JWT to resolve org_id from otherwise,
    # and needs it before it can even open an org-scoped DB session.
    callback_url = f"{settings.app_public_url.rstrip('/')}/external/webhooks/pesapal"
    try:
        intent = await PesapalProvider(config).create_payment_intent(
            charged_cents,
            invoice.currency,
            {
                "merchant_reference": f"{principal.org_id}:{invoice.id}",
                "callback_url": callback_url,
                "description": f"POS sale {invoice.number}",
                "email": principal.email,
            },
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        invoice.status = "void"
        await session.commit()
        raise HTTPException(502, f"Could not start Pesapal checkout: {exc}") from exc

    return PayWithPesapalOut(invoice_id=invoice.id, redirect_url=intent["redirect_url"])


@pos_router.post("/sales/pay-with-paystack", response_model=PaystackCheckoutOut, status_code=201)
async def pay_with_paystack(
    body: dict,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    """A POS sale paid through the business's own Paystack (card, M-Pesa,
    bank). Like pay_with_pesapal: the sale waits as "pending" until
    Paystack's verify says it was paid (paystack_pay.settle, reached from
    the webhook or the till's status poll). Online only. A split sale
    sends the till's own part as "payments" (cash, M-Pesa, card): it is
    recorded now and Paystack charges the rest."""
    now = datetime.now(UTC)
    lines_in = body.get("lines", [])
    if not lines_in:
        raise HTTPException(422, "sale must have at least one line")
    shift_id = await shift_for_sale(session, principal, body.get("shift_id"))
    location_id = await till_location(session, shift_id)
    at_place(scope, location_id)
    invoice = Invoice(
        org_id=uuid.UUID(principal.org_id),
        number=f"POS-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        status="pending",
        currency=body.get("currency", "USD"),
        source="pos",
        source_ref=body.get("client_sale_id"),
        cashier_user_id=principal.user_id,
        cashier_email=principal.email,
        pos_shift_id=shift_id,
        location_id=location_id,
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(invoice)
    await session.flush()
    charged_cents = await _apply_pos_sale_lines(session, principal, invoice, lines_in, body)
    if charged_cents <= 0:
        raise HTTPException(422, "nothing to charge")
    to_charge = await manual_tenders(session, principal, invoice, body.get("payments") or [], charged_cents)
    customer_email = str(body.get("email") or "")
    if body.get("phone"):
        # M-Pesa prompt straight to the customer's phone: no Paystack page.
        prompt = await start_mpesa_prompt(
            principal.org_id, invoice, to_charge, str(body["phone"]), customer_email, principal.email or ""
        )
        await session.commit()
        return PaystackCheckoutOut(invoice_id=invoice.id, prompt=prompt)
    redirect_url = await start_paystack_checkout(
        principal.org_id, invoice, to_charge, customer_email, principal.email or "", f"POS sale {invoice.number}"
    )
    await session.commit()
    return PaystackCheckoutOut(invoice_id=invoice.id, redirect_url=redirect_url)


@pos_router.get("/sales/{invoice_id}/status", response_model=PosSaleStatusOut)
async def get_pos_sale_status(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    """Lightweight poll target for the frontend while a Pesapal payment is
    in flight -- the register shows a waiting state until this flips from
    "pending" to "paid" (or "void" on failure)."""
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None or str(invoice.org_id) != principal.org_id:
        raise HTTPException(404, "sale not found")
    if invoice.status != "paid" and invoice.paystack_reference:
        # Ask Paystack directly, so a sale settles even if its webhook is lost.
        reference = invoice.paystack_reference
        try:
            await settle_paystack(session, principal.org_id, str(invoice.id), reference)
        except httpx.HTTPError as exc:
            logger.warning("paystack verify %s failed: %s", reference, exc)
        invoice = await session.get(Invoice, invoice_id, populate_existing=True)
    return PosSaleStatusOut(invoice_id=invoice.id, status=invoice.status)


async def _returnable(session: AsyncSession, principal: Principal, original: Invoice) -> dict[str, Decimal]:
    """How much of each line of a sale can still come back: its quantity
    minus what earlier returns (RET- documents naming this sale) took.
    A return line is matched to the sale line it mirrors."""
    rows = await session.execute(
        select(Invoice)
        .where(
            Invoice.org_id == uuid.UUID(principal.org_id),
            Invoice.source == "pos",
            Invoice.source_ref == original.number,
            Invoice.number.like("RET-%"),
        )
        .options(selectinload(Invoice.lines))
    )
    left = {str(l.id): Decimal(str(l.quantity)) for l in original.lines}
    for ret in rows.scalars().all():
        for r in ret.lines:
            for l in original.lines:
                key = str(l.id)
                same = (
                    r.description == f"Return: {l.description}"
                    and r.product_id == l.product_id
                    and r.unit_price_cents == l.unit_price_cents
                )
                if same and left[key] > 0:
                    took = min(left[key], -Decimal(str(r.quantity)))
                    left[key] -= took
                    break
    return left


async def _get_pos_sale(session: AsyncSession, principal: Principal, number: str) -> Invoice:
    rows = await session.execute(
        select(Invoice).where(
            Invoice.org_id == uuid.UUID(principal.org_id), Invoice.number == number, Invoice.source == "pos"
        )
    )
    inv = rows.scalars().first()
    if inv is None and len(number.strip()) >= 8:
        # The receipt shows the start of the till's own sale id (printed
        # before the server numbers the sale, e.g. offline).
        ref = number.strip().lower()
        rows = await session.execute(
            select(Invoice).where(
                Invoice.org_id == uuid.UUID(principal.org_id),
                Invoice.source == "pos",
                Invoice.number.like("POS-%"),
                Invoice.source_ref.like(ref.replace("%", "").replace("_", "") + "%"),
            )
        )
        found = rows.scalars().all()
        inv = found[0] if len(found) == 1 else None
    if inv is None:
        raise HTTPException(404, "pos sale not found")
    return inv


@pos_router.get("/sales")
async def list_pos_sales(
    day: date = Query(..., description="YYYY-MM-DD, in UTC"),
    channel: str | None = Query(None, pattern="^(till|guss)$"),
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("sales.read")),
    session: AsyncSession = Depends(get_org_session),
):
    """One day's sales from every till and Guss, newest first: what Guss
    reads back to answer "what did we sell today". Returns are included
    as negative sales."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    q = select(Invoice).where(
        Invoice.org_id == uuid.UUID(principal.org_id),
        Invoice.source == "pos",
        Invoice.issued_at >= start,
        Invoice.issued_at < start + timedelta(days=1),
        Invoice.status.in_(("paid", "void")),
    )
    if channel:
        q = q.where(Invoice.channel == channel)
    # Staff see their own, team leaders their team's, branch managers their
    # locations' (plan 12.2).
    q = _in_scope(q, scope)
    rows = (await session.execute(q.order_by(Invoice.issued_at.desc()).limit(500))).scalars().all()
    return [
        {
            "number": inv.number,
            "channel": inv.channel,
            "status": inv.status,
            "issued_at": inv.issued_at,
            "cashier": inv.cashier_email or "",
            "currency": inv.currency,
            "total_cents": sum(line.total_cents + line.tax_cents for line in inv.lines),
            "payments": [{"method": p.method, "cents": p.amount_cents} for p in inv.payments],
            "lines": [
                {"description": line.description, "quantity": float(line.quantity), "product_id": line.product_id}
                for line in inv.lines
                if not line.is_adjustment
            ],
        }
        for inv in rows
    ]


@pos_router.get("/sales/{number}", response_model=InvoiceOut)
async def get_pos_sale(
    number: str,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("pos.sell")),
    session: AsyncSession = Depends(get_org_session),
):
    """Looks up a past sale by receipt number -- what the POS register's
    returns screen calls before offering to refund it."""
    inv = await _get_pos_sale(session, principal, number)
    at_place(scope, inv.location_id, "that sale")
    return InvoiceOut.from_model(inv)


@pos_router.post("/sales/{number}/return", response_model=InvoiceOut, status_code=201)
async def return_pos_sale(
    number: str,
    request: Request,
    shift_id: uuid.UUID | None = None,
    body: dict | None = None,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("pos.sell")),
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
    at_place(scope, original.location_id, "that sale")
    # Staff need a team leader's or manager's PIN at the till (plan 12.2),
    # within their limit; the whole sale's total is the most it can be.
    approved_by = None
    if principal.role == "member":
        await session.refresh(original, attribute_names=["lines"])
        approved_by = check_approval(
            request.headers.get(APPROVAL_HEADER),
            principal,
            amount_cents=original.grand_total_cents,
            location_id=str(original.location_id) if original.location_id else None,
        )
    # Sent again with the same client_return_id (a retry whose reply was
    # lost): the refund it made, never a second one. The refund's Payment
    # carries the id.
    client_return_id = str((body or {}).get("client_return_id") or "").strip()[:120] or None
    if client_return_id:
        done = await session.scalar(
            select(Invoice)
            .join(Payment, Payment.invoice_id == Invoice.id)
            .where(Invoice.org_id == uuid.UUID(principal.org_id), Payment.client_ref == client_return_id)
            .options(selectinload(Invoice.lines), selectinload(Invoice.payments))
        )
        if done is not None:
            return InvoiceOut.from_model(done)
    if original.status == "void":
        raise HTTPException(400, "sale is already void")
    await session.refresh(original, attribute_names=["lines", "payments"])

    # What's still returnable per line (earlier partial returns are RET-
    # documents pointing at this sale), and what this return takes:
    # {"lines": [{"line_id": ..., "quantity": 1}]}, or everything left.
    left = await _returnable(session, principal, original)
    wanted = {str(x.get("line_id")): Decimal(str(x.get("quantity", 0))) for x in (body or {}).get("lines") or []}
    if wanted:
        for line_id, qty in wanted.items():
            if line_id not in left or qty <= 0 or qty > left[line_id]:
                raise HTTPException(422, "return between 0 and what's left of that line")
    take = wanted or {k: v for k, v in left.items() if v > 0}
    if not take:
        raise HTTPException(400, "everything on this sale was already returned")
    everything = all(take.get(k, 0) == v for k, v in left.items())

    if original.status == "sent":
        # A credit sale nobody has paid: no money came in, so none goes
        # out. Taking it all back cancels it and restocks.
        if original.payments or not everything:
            raise HTTPException(409, "this sale is on credit: take it all back, or record the payment first")
        original.status = "void"
        original.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(original, attribute_names=["lines", "payments"])
        back = SimpleNamespace(
            number=original.number,
            cashier_user_id=original.cashier_user_id,
            cashier_email=original.cashier_email,
            location_id=original.location_id,
            lines=[
                SimpleNamespace(product_id=l.product_id, quantity=-l.quantity, unit_cost_cents=l.unit_cost_cents, uom_factor=l.uom_factor)
                for l in original.lines
            ],
        )
        await publish_pos_sale_recorded(principal.org_id, back, 0)
        return InvoiceOut.from_model(original)

    now = datetime.now(UTC)
    refund = Invoice(
        org_id=uuid.UUID(principal.org_id),
        number=f"RET-{now:%Y%m%d}-{uuid.uuid4().hex[:6].upper()}",
        status="paid",
        currency=original.currency,
        source="pos",
        source_ref=original.number,
        cashier_user_id=principal.user_id,
        cashier_email=principal.email,
        pos_shift_id=await shift_for_sale(session, principal, shift_id),
        location_id=original.location_id,
        approved_by=approved_by or "",
        issued_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(refund)
    await session.flush()

    refund_total_cents = 0
    for line in original.lines:
        qty = take.get(str(line.id))
        if not qty:
            continue
        # The share of the line's own total and VAT, so a partial return
        # of a discounted line gives back what was actually paid.
        share = qty / Decimal(str(line.quantity))
        line_total = int((Decimal(line.total_cents) * share).quantize(Decimal(1), ROUND_HALF_UP))
        line_vat = int((Decimal(line.vat_cents or 0) * share).quantize(Decimal(1), ROUND_HALF_UP))
        refund_total_cents += -line_total
        session.add(
            InvoiceLine(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=refund.id,
                description=f"Return: {line.description}",
                quantity=-qty,
                unit_price_cents=line.unit_price_cents,
                discount_bp=line.discount_bp,
                unit_cost_cents=line.unit_cost_cents,
                product_id=line.product_id,
                tax_code=line.tax_code,
                vat_cents=-line_vat,
                is_adjustment=line.is_adjustment,
                item_code=line.item_code,
                item_class=line.item_class,
                quantity_unit=line.quantity_unit,
                packaging_unit=line.packaging_unit,
                uom_name=line.uom_name,
                uom_factor=line.uom_factor,
                etims_qty_factor=line.etims_qty_factor,
            )
        )
    # A credit note on eTIMS names the same buyer as the sale.
    refund.buyer_pin = original.buyer_pin
    refund.buyer_name = original.buyer_name
    refund.prices_include_tax = original.prices_include_tax

    # A sale paid through Paystack is refunded through Paystack (and booked
    # back out of M-Pesa/card); anything else comes out of the drawer.
    await session.flush()
    online = await refund_share(session, principal.org_id, original, -refund_total_cents)
    online_cents = online[1] if online else 0
    if online:
        session.add(
            Payment(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=refund.id,
                amount_cents=-online_cents,
                method=online[0],
                received_at=now,
                client_ref=client_return_id,
            )
        )
    if refund_total_cents + online_cents != 0:
        session.add(
            Payment(
                org_id=uuid.UUID(principal.org_id),
                invoice_id=refund.id,
                amount_cents=refund_total_cents + online_cents,
                method="refund",
                received_at=now,
                client_ref=client_return_id,
            )
        )
    # A partial return leaves the sale standing for what the customer kept.
    if everything:
        original.status = "void"
    original.updated_at = now

    await session.commit()
    await session.refresh(refund, attribute_names=["lines", "payments"])

    await publish_pos_sale_recorded(principal.org_id, refund, refund_total_cents)
    # Negative paid_amount_cents -- Accounting's invoice-paid webhook
    # mirrors the debit/credit sides for a negative amount so the ledger
    # itself never carries a negative entry.
    await publish_invoice_paid(principal.org_id, refund, refund_total_cents, invoice_lines_payload(refund))

    return InvoiceOut.from_model(refund)


@invoices_router.post("/{invoice_id}/credit-note", response_model=InvoiceOut, status_code=201)
async def create_credit_note(
    invoice_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Credit notes as a first-class concept for manual invoices -- same
    negated-lines pattern return_pos_sale already established for POS
    refunds, applied here instead of editing the original invoice (which
    stays exactly as issued; a credit note is a new document, same as
    every real-world accounting system treats it). Unlike a POS return,
    the original isn't voided -- a credit note can be partial, or issued
    against an invoice that was never actually paid in full."""
    original = await _get_invoice(session, principal, invoice_id, scope=scope)
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


# --- Quotes (P1 quote-to-cash) ------------------------------------------

quotes_router = APIRouter(prefix="/quotes", tags=["quotes"])
reports_router = APIRouter(prefix="/reports", tags=["reports"])


def _copy_line(org_id: uuid.UUID, document_id: uuid.UUID, line) -> InvoiceLine:
    """One place that knows every InvoiceLine field, used for quote
    creation (from LineIn) and quote -> invoice conversion (from an
    existing InvoiceLine) so a converted invoice can't silently drop a
    field the quote had (tax, discount, cost basis, product link)."""
    return InvoiceLine(
        org_id=org_id,
        invoice_id=document_id,
        description=line.description,
        quantity=line.quantity,
        unit_price_cents=line.unit_price_cents,
        tax_rate_bp=line.tax_rate_bp,
        discount_bp=line.discount_bp,
        unit_cost_cents=line.unit_cost_cents,
        product_id=line.product_id,
    )


@quotes_router.get("", response_model=list[InvoiceOut])
async def list_quotes(
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("invoices.read")),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Invoice)
        .where(Invoice.org_id == uuid.UUID(principal.org_id), Invoice.kind == "quote")
        .order_by(Invoice.created_at.desc())
    )
    return [InvoiceOut.from_model(q) for q in rows.scalars().all()]


@quotes_router.post("", response_model=InvoiceOut, status_code=201)
async def create_quote(
    body: QuoteCreate,
    principal: Principal = Depends(get_current_principal),
    _scope: Scope = Depends(require("invoices.write")),
    session: AsyncSession = Depends(get_org_session),
):
    org_id = uuid.UUID(principal.org_id)
    if body.customer_id is not None:
        customer = await session.get(Customer, body.customer_id)
        if customer is None or customer.org_id != org_id:
            raise HTTPException(404, "customer not found")
    now = datetime.now(UTC)
    quote = Invoice(
        org_id=org_id,
        customer_id=body.customer_id,
        kind="quote",
        number=f"QUO-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        currency=body.currency,
        source="crm" if body.opportunity_id else "manual",
        source_ref=body.opportunity_id,
        valid_until=now + timedelta(days=body.valid_days),
        created_at=now,
        updated_at=now,
    )
    session.add(quote)
    await session.flush()
    for line in body.lines:
        session.add(_copy_line(org_id, quote.id, line))
    await session.commit()
    await session.refresh(quote, attribute_names=["lines", "payments"])
    return InvoiceOut.from_model(quote)


@quotes_router.get("/{quote_id}", response_model=InvoiceOut)
async def get_quote(
    quote_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.read")),
    session: AsyncSession = Depends(get_org_session),
):
    return InvoiceOut.from_model(await _get_invoice(session, principal, quote_id, kind="quote", scope=scope))


@quotes_router.patch("/{quote_id}/status", response_model=InvoiceOut)
async def set_quote_status(
    quote_id: uuid.UUID,
    body: QuoteStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.write")),
    session: AsyncSession = Depends(get_org_session),
):
    if body.status not in QUOTE_MANUAL_STATUSES:
        raise HTTPException(
            422, f"status must be one of {QUOTE_MANUAL_STATUSES} (accept a quote by converting it to an invoice)"
        )
    quote = await _get_invoice(session, principal, quote_id, kind="quote", scope=scope)
    if quote.status == "accepted":
        raise HTTPException(409, "this quote was already converted to an invoice")
    quote.status = body.status
    quote.updated_at = datetime.now(UTC)
    if body.status == "sent" and quote.issued_at is None:
        quote.issued_at = quote.updated_at
    await session.commit()
    await session.refresh(quote, attribute_names=["lines", "payments"])
    return InvoiceOut.from_model(quote)


@quotes_router.post("/{quote_id}/convert", response_model=InvoiceOut, status_code=201)
async def convert_quote(
    quote_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.write")),
    session: AsyncSession = Depends(get_org_session),
):
    """Customer accepted: create a draft invoice with the quote's exact
    lines, mark the quote accepted, link both ways (invoice.source =
    "quote", source_ref = quote id). The invoice starts as draft so the
    user reviews it before "sent" emails the customer."""
    quote = await _get_invoice(session, principal, quote_id, kind="quote", scope=scope)
    if quote.status in ("accepted", "declined"):
        raise HTTPException(409, f"quote is already {quote.status}")
    now = datetime.now(UTC)
    if quote.valid_until is not None and quote.valid_until < now:
        raise HTTPException(409, f"quote expired on {quote.valid_until:%Y-%m-%d} -- issue a new quote")

    org_id = uuid.UUID(principal.org_id)
    due_at = None
    if quote.customer_id is not None:
        customer = await session.get(Customer, quote.customer_id)
        if customer is not None:
            due_at = now + timedelta(days=customer.payment_terms_days)
    invoice = Invoice(
        org_id=org_id,
        customer_id=quote.customer_id,
        kind="invoice",
        number=f"INV-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        currency=quote.currency,
        source="quote",
        source_ref=str(quote.id),
        due_at=due_at,
        created_at=now,
        updated_at=now,
    )
    session.add(invoice)
    await session.flush()
    for line in quote.lines:
        session.add(_copy_line(org_id, invoice.id, line))
    quote.status = "accepted"
    quote.updated_at = now
    await session.commit()
    await session.refresh(invoice, attribute_names=["lines", "payments"])
    return InvoiceOut.from_model(invoice)


# --- Reports ------------------------------------------------------------

_AGING_BUCKETS = (
    (0, "current_cents"),
    (30, "days_1_30_cents"),
    (60, "days_31_60_cents"),
    (90, "days_61_90_cents"),
)


def _aging_bucket(days_past_due: int) -> str:
    for limit, name in _AGING_BUCKETS:
        if days_past_due <= limit:
            return name
    return "days_over_90_cents"


@reports_router.get("/ar-aging", response_model=ArAgingOut)
async def ar_aging(
    principal: Principal = Depends(get_current_principal),
    scope: Scope = Depends(require("invoices.read")),
    session: AsyncSession = Depends(get_org_session),
):
    if not scope.everywhere:
        raise HTTPException(403, "the receivables report covers the whole business; ask an admin")
    """Accounts-receivable aging: what customers owe and how late it is.
    Only issued invoices (status "sent") with an outstanding balance --
    drafts aren't owed yet, paid/void owe nothing. No due date = current."""
    now = datetime.now(UTC)
    org_id = uuid.UUID(principal.org_id)
    invoices = (
        await session.execute(
            select(Invoice).where(Invoice.org_id == org_id, Invoice.kind == "invoice", Invoice.status == "sent")
        )
    ).scalars().all()
    customers = {
        c.id: c.name
        for c in (await session.execute(select(Customer).where(Customer.org_id == org_id))).scalars().all()
    }

    rows: dict[tuple, ArAgingCustomerRow] = {}
    totals: dict[str, ArAgingCurrencyTotals] = {}
    for inv in invoices:
        balance = inv.balance_cents
        if balance <= 0:
            continue
        days = (now - inv.due_at).days if inv.due_at is not None else 0
        bucket = _aging_bucket(days)
        key = (inv.customer_id, inv.currency)
        row = rows.get(key) or ArAgingCustomerRow(
            customer_id=inv.customer_id,
            customer_name=customers.get(inv.customer_id, "No customer") if inv.customer_id else "No customer",
            currency=inv.currency,
        )
        rows[key] = row
        total = totals.get(inv.currency) or ArAgingCurrencyTotals(currency=inv.currency)
        totals[inv.currency] = total
        for target in (row, total):
            setattr(target, bucket, getattr(target, bucket) + balance)
            target.total_cents += balance
        row.invoice_count += 1

    return ArAgingOut(
        as_of=now,
        rows=sorted(rows.values(), key=lambda r: (r.currency, -r.total_cents)),
        totals=sorted(totals.values(), key=lambda t: t.currency),
    )


app.include_router(customers_router)
app.include_router(
    import_router(
        [
            ImportTarget(
                "customer",
                "Customers",
                "customers",
                (
                    ImportField("name", "Name", required=True),
                    ImportField("email", "Email", "email"),
                    ImportField("company", "Company"),
                    ImportField("payment_terms_days", "Payment terms (days)", "int"),
                ),
            )
        ]
    )
)
app.include_router(invoices_router)
app.include_router(quotes_router)
app.include_router(reports_router)
app.include_router(pos_router)
app.include_router(credit_router)
app.include_router(paystack_router)
app.include_router(registers_router)
app.include_router(etims_router)
app.include_router(webhooks_router)
app.include_router(external_router)
