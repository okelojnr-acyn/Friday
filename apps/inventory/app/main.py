import hashlib
import math
import uuid
from decimal import Decimal
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from friday_common.importer import ImportField, ImportTarget, import_router
from friday_common import (
    first_delivery,
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_org_session,
    get_session,
    require_kernel_token,
    resource,
    set_org_context,
)
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .etims import router as etims_router
from .purchases import price_purchase_vat, publish_purchase_received
from .purchases import router as purchases_router
from .uom import fixed_factor, settle_units
from .uom import router as uoms_router
from .models import (
    ProductImage,
    PRODUCT_KINDS,
    PURCHASE_ORDER_STATUSES,
    REASONS,
    VALUATION_METHODS,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    StockMove,
    Supplier,
    UnitOfMeasure,
    Warehouse,
)
from .schemas import (
    ProductBulkCreate,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    PurchaseOrderCreate,
    PurchaseOrderOut,
    PurchaseOrderStatusUpdate,
    StockAdjust,
    StockMoveOut,
    SupplierCreate,
    SupplierOut,
    WarehouseCreate,
    WarehouseOut,
)

resource(
    ResourceSpec(
        name="product",
        app="inventory",
        label="Product",
        label_plural="Products",
        views=("list", "form"),
        search_fields=("name", "sku", "barcode"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("kind", "Kind", "select", options=PRODUCT_KINDS, required=True),
            FieldSpec("sku", "SKU", "text"),
            FieldSpec("barcode", "Barcode", "text"),
            FieldSpec("category", "Category", "text"),
            FieldSpec("price_cents", "Price", "currency", required=True),
            FieldSpec("cost_cents", "Cost", "currency"),
            FieldSpec("on_hand_qty", "On hand", "number", form_visible=False),
            FieldSpec("reorder_point", "Reorder at", "number"),
            FieldSpec("track_inventory", "Tracks stock", "boolean"),
            FieldSpec(
                "default_warehouse_id",
                "Default warehouse",
                "reference",
                reference="inventory.warehouse",
                list_visible=False,
            ),
            FieldSpec("uom_id", "Unit of measure", "reference", reference="inventory.unit_of_measure", list_visible=False),
            FieldSpec("uom_conversion_factor", "UoM conversion factor", "number", list_visible=False),
            FieldSpec("valuation_method", "Valuation method", "select", options=VALUATION_METHODS, list_visible=False),
            FieldSpec("tax_code", "Tax type (eTIMS)", "select", options=("", "A", "B", "C", "D", "E"), list_visible=False),
            FieldSpec("etims_item_class", "eTIMS item classification", "text", list_visible=False),
            FieldSpec("etims_packaging_unit", "eTIMS packaging unit", "text", list_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="warehouse",
        app="inventory",
        label="Warehouse",
        label_plural="Warehouses",
        views=("list", "form"),
        search_fields=("name", "code"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("code", "Code", "text"),
            FieldSpec("address", "Address", "text"),
            FieldSpec("is_default", "Default", "boolean"),
            FieldSpec("created_at", "Added", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="unit_of_measure",
        app="inventory",
        label="Unit of Measure",
        label_plural="Units of Measure",
        views=("list", "form"),
        search_fields=("name", "abbreviation"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("abbreviation", "Abbreviation", "text"),
            FieldSpec("created_at", "Added", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="stock_move",
        app="inventory",
        label="Stock Move",
        label_plural="Stock Moves",
        views=("list",),
        search_fields=("product_name", "reference"),
        fields=(
            FieldSpec("product_name", "Product", "text", required=True),
            FieldSpec("qty_delta", "Change", "number", required=True),
            FieldSpec("reason", "Reason", "select", options=REASONS, required=True),
            FieldSpec("reference", "Reference", "text"),
            FieldSpec("created_at", "When", "datetime"),
        ),
    )
)

resource(
    ResourceSpec(
        name="supplier",
        app="inventory",
        label="Supplier",
        label_plural="Suppliers",
        views=("list", "form"),
        search_fields=("name", "email"),
        fields=(
            FieldSpec("name", "Name", "text", required=True),
            FieldSpec("email", "Email", "email"),
            FieldSpec("phone", "Phone", "phone"),
            FieldSpec("kra_pin", "KRA PIN", "text"),
            FieldSpec("created_at", "Added", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="purchase_order",
        app="inventory",
        label="Purchase Order",
        label_plural="Purchase Orders",
        views=("list", "form"),
        search_fields=("number",),
        fields=(
            FieldSpec("number", "Number", "text", form_visible=False),
            FieldSpec("supplier_id", "Supplier", "reference", reference="inventory.supplier", form_visible=False),
            FieldSpec("status", "Status", "select", options=PURCHASE_ORDER_STATUSES, required=True),
            FieldSpec("total_cost_cents", "Total cost", "currency", form_visible=False),
            FieldSpec("paid_at", "Paid", "datetime", form_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

app = create_app("friday-inventory")

products_router = APIRouter(prefix="/products", tags=["products"])
moves_router = APIRouter(prefix="/stock_moves", tags=["stock-moves"])
suppliers_router = APIRouter(prefix="/suppliers", tags=["suppliers"])
purchase_orders_router = APIRouter(prefix="/purchase_orders", tags=["purchase-orders"])
warehouses_router = APIRouter(prefix="/warehouses", tags=["warehouses"])
webhooks_router = APIRouter(prefix="/internal/webhooks", tags=["webhooks"])


def _org(principal: Principal) -> uuid.UUID:
    return uuid.UUID(principal.org_id)


async def purchase_unit_for(
    session: AsyncSession, org: uuid.UUID, product_id: uuid.UUID | None, uom_id: uuid.UUID | None, factor: Decimal | None
) -> tuple[uuid.UUID | None, str, Decimal]:
    """The unit a purchase order line is in and its base units per unit:
    as given, or the product's purchase unit. Copied onto the line."""
    product = await session.get(Product, product_id) if product_id else None
    if product is not None and product.org_id != org:
        product = None
    unit_id = uom_id or (product.purchase_uom_id if product else None)
    unit = await session.get(UnitOfMeasure, unit_id) if unit_id else None
    if unit is not None and unit.org_id != org:
        raise HTTPException(422, "uom_id: that unit isn't in this organisation")
    if factor is not None:
        if factor <= 0:
            raise HTTPException(422, "uom_factor must be more than 0")
        f = Decimal(factor)
    elif product is not None and unit is not None and unit.id == product.purchase_uom_id:
        f = Decimal(product.purchase_factor)
    elif product is not None and unit is not None and product.base_uom_id:
        base = await session.get(UnitOfMeasure, product.base_uom_id)
        f = fixed_factor(base, unit) if base else None
        if f is None:
            raise HTTPException(422, f"how many base units are in one {unit.name.lower()}? Give uom_factor")
    else:
        f = Decimal(1)
    return (unit.id if unit else None), (unit.abbreviation or unit.name if unit else ""), f


@products_router.get("", response_model=list[ProductOut])
async def list_products(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Product).where(Product.org_id == _org(principal)).order_by(Product.name)
    )
    return rows.scalars().all()


def _product_fields(body: ProductCreate) -> dict:
    """Shared by create_product and the bulk endpoint: validates `kind`
    and forces track_inventory=False for a service regardless of what
    the client sent -- a service's on_hand_qty is never meaningful (see
    Product.kind's doc comment), so this isn't optional client-side
    behavior to get right, it's enforced here."""
    if body.kind not in PRODUCT_KINDS:
        raise HTTPException(422, f"kind must be one of {PRODUCT_KINDS}")
    if body.valuation_method not in VALUATION_METHODS:
        raise HTTPException(422, f"valuation_method must be one of {VALUATION_METHODS}")
    data = body.model_dump()
    for f in ("purchase_factor", "sales_factor"):
        if data.get(f) is None:
            data.pop(f, None)  # settle_units works it out
    if body.kind == "service":
        data["track_inventory"] = False
    return data


@products_router.post("", response_model=ProductOut, status_code=201)
async def create_product(
    body: ProductCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    await _check_variant_of(session, principal, body.variant_of)
    now = datetime.now(UTC)
    product = Product(org_id=_org(principal), created_at=now, updated_at=now, **_product_fields(body))
    await settle_units(session, _org(principal), product, body.model_dump(exclude_unset=True))
    session.add(product)
    await session.flush()
    if product.on_hand_qty:
        session.add(
            StockMove(
                org_id=_org(principal),
                product_id=product.id,
                product_name=product.name,
                qty_delta=product.on_hand_qty,
                reason="received",
                reference="initial stock",
                warehouse_id=product.default_warehouse_id,
                created_at=now,
            )
        )
    await session.commit()
    await session.refresh(product)
    return product


async def _check_variant_of(
    session: AsyncSession, principal: Principal, variant_of: uuid.UUID | None, self_id: uuid.UUID | None = None
) -> None:
    """A variant points at a product of the same org that isn't itself a
    variant (one level: Sugar -> 1 kg, not Sugar -> 1 kg -> brown)."""
    if variant_of is None:
        return
    if self_id is not None and variant_of == self_id:
        raise HTTPException(422, "a product can't be a variant of itself")
    parent = await session.get(Product, variant_of)
    if parent is None or str(parent.org_id) != principal.org_id:
        raise HTTPException(422, "variant_of: that product isn't in this organisation")
    if parent.variant_of is not None:
        raise HTTPException(422, "variant_of: pick the main product, not another variant")
    if self_id is not None:
        has_variants = (
            await session.execute(select(Product.id).where(Product.variant_of == self_id).limit(1))
        ).first()
        if has_variants:
            raise HTTPException(422, "this product has variants of its own, so it can't be a variant")


async def _get_owned(session: AsyncSession, principal: Principal, product_id: uuid.UUID) -> Product:
    product = await session.get(Product, product_id)
    if product is None or str(product.org_id) != principal.org_id:
        raise HTTPException(404, "product not found")
    return product


@products_router.get("/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    return await _get_owned(session, principal, product_id)


@products_router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID,
    body: ProductUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    product = await _get_owned(session, principal, product_id)
    changes = body.model_dump(exclude_unset=True)
    if "kind" in changes and changes["kind"] not in PRODUCT_KINDS:
        raise HTTPException(422, f"kind must be one of {PRODUCT_KINDS}")
    if "valuation_method" in changes and changes["valuation_method"] not in VALUATION_METHODS:
        raise HTTPException(422, f"valuation_method must be one of {VALUATION_METHODS}")
    if "variant_of" in changes:
        await _check_variant_of(session, principal, changes["variant_of"], product.id)
    for field_name, value in changes.items():
        if field_name in ("purchase_factor", "sales_factor") and value is None:
            continue
        setattr(product, field_name, value)
    if {"base_uom_id", "purchase_uom_id", "sales_uom_id", "purchase_factor", "sales_factor"} & changes.keys() or product.base_uom_id is None:
        await settle_units(session, _org(principal), product, changes)
    if product.kind == "service":
        product.track_inventory = False
    product.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(product)
    return product


IMAGE_TYPES = {"image/webp", "image/jpeg", "image/png"}
MAX_IMAGE_BYTES = 400 * 1024


@products_router.put("/{product_id}/image", response_model=ProductOut)
async def put_product_image(
    product_id: uuid.UUID,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The product's photo, as the raw image body. The web app resizes it
    to 512 px first; 400 KB is the ceiling."""
    if principal.role == "viewer":
        raise HTTPException(403, "viewers can't change photos")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in IMAGE_TYPES:
        raise HTTPException(415, "send a WebP, JPEG or PNG image")
    data = await request.body()
    if not data:
        raise HTTPException(422, "the image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "the photo is over 400 KB; it should be resized before upload")
    product = await _get_owned(session, principal, product_id)
    now = datetime.now(UTC)
    image = await session.get(ProductImage, product.id)
    if image is None:
        session.add(ProductImage(product_id=product.id, org_id=product.org_id, content_type=content_type, data=data, updated_at=now))
    else:
        image.content_type, image.data, image.updated_at = content_type, data, now
    product.image_sha = hashlib.sha256(data).hexdigest()[:16]
    product.updated_at = now
    await session.commit()
    await session.refresh(product)
    return product


@products_router.delete("/{product_id}/image", response_model=ProductOut)
async def delete_product_image(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if principal.role == "viewer":
        raise HTTPException(403, "viewers can't change photos")
    product = await _get_owned(session, principal, product_id)
    image = await session.get(ProductImage, product.id)
    if image is not None:
        await session.delete(image)
    product.image_sha = ""
    product.updated_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(product)
    return product


@products_router.get("/{product_id}/image")
async def get_product_image(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The photo. Fetched with ?v=<image_sha>, so it can be cached for good."""
    await _get_owned(session, principal, product_id)
    image = await session.get(ProductImage, product_id)
    if image is None:
        raise HTTPException(404, "no photo")
    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@products_router.post("/bulk", response_model=list[ProductOut], status_code=201)
async def bulk_create_products(
    body: ProductBulkCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The bulk-add screen's one call (see web/src/apps/inventory/
    BulkAddProductsPanel.tsx): scan/type a batch of products or
    services and create them all in one request instead of one
    round trip per row."""
    now = datetime.now(UTC)
    created: list[Product] = []
    for item in body.products:
        await _check_variant_of(session, principal, item.variant_of)
        product = Product(org_id=_org(principal), created_at=now, updated_at=now, **_product_fields(item))
        await settle_units(session, _org(principal), product, item.model_dump(exclude_unset=True))
        session.add(product)
        created.append(product)
    await session.flush()
    for product in created:
        if product.on_hand_qty:
            session.add(
                StockMove(
                    org_id=_org(principal),
                    product_id=product.id,
                    product_name=product.name,
                    qty_delta=product.on_hand_qty,
                    reason="received",
                    reference="bulk add",
                    warehouse_id=product.default_warehouse_id,
                    created_at=now,
                )
            )
    await session.commit()
    for product in created:
        await session.refresh(product)
    return created


@products_router.post("/{product_id}/adjust-stock", response_model=ProductOut)
async def adjust_stock(
    product_id: uuid.UUID,
    body: StockAdjust,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The one way on_hand_qty ever changes by hand -- always alongside a
    StockMove row, so the ledger and the cached count never drift apart."""
    if body.reason not in REASONS:
        raise HTTPException(422, f"reason must be one of {REASONS}")
    product = await _get_owned(session, principal, product_id)
    now = datetime.now(UTC)
    product.on_hand_qty = Decimal(product.on_hand_qty) + body.delta
    product.updated_at = now
    session.add(
        StockMove(
            org_id=_org(principal),
            product_id=product.id,
            product_name=product.name,
            qty_delta=body.delta,
            reason=body.reason,
            reference=body.reference,
            warehouse_id=body.warehouse_id or product.default_warehouse_id,
            created_at=now,
        )
    )
    await session.commit()
    await session.refresh(product)
    return product


@moves_router.get("", response_model=list[StockMoveOut])
async def list_stock_moves(
    reference: str | None = None,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """All moves, newest first; `?reference=` narrows to one reference
    (Guss checks "guss:<entry id>" before recording, so a retry never
    counts twice)."""
    query = select(StockMove).where(StockMove.org_id == _org(principal))
    if reference is not None:
        query = query.where(StockMove.reference == reference)
    rows = await session.execute(query.order_by(StockMove.created_at.desc()))
    return rows.scalars().all()


@webhooks_router.post("/pos-sale", dependencies=[Depends(require_kernel_token)], status_code=204)
async def pos_sale_recorded(body: dict, session: AsyncSession = Depends(get_session)):
    """Subscribed to invoicing.pos_sale.recorded (see
    kernel/internal/gateway/events.go) -- automatically decrements stock
    for every sold line that was rung up from the product catalog
    (freeform/ad-hoc POS lines carry no product_id and are skipped)."""
    payload = body.get("payload", {})
    org_id = uuid.UUID(body["org_id"])
    await set_org_context(session, str(org_id))
    # The kernel retries until a delivery succeeds; a repeat is skipped.
    if not await first_delivery(session, body):
        return
    now = datetime.now(UTC)
    reference = str(payload.get("invoice_number", ""))

    # One total per product: a sale can carry the same product on two
    # lines (one discounted). A line is in the unit it was sold in; its
    # uom_factor (base units per sold unit, copied at sale time) turns it
    # into base units. A line from before units has none: the product's
    # sales unit applies (worked out in SQL below). Nothing is rounded to
    # whole units any more: 0.5 kg takes 0.5 kg off.
    per_product: dict[str, dict[str, Decimal]] = {}
    for line in payload.get("lines", []):
        product_id = line.get("product_id")
        if not product_id:
            continue
        q = Decimal(str(line.get("quantity", 0) or 0))
        f = line.get("uom_factor")
        totals = per_product.setdefault(product_id, {"base": Decimal(0), "sold": Decimal(0)})
        if f not in (None, ""):
            totals["base"] += q * Decimal(str(f))
        else:
            totals["sold"] += q

    for product_id, totals in per_product.items():
        if totals["base"] == 0 and totals["sold"] == 0:
            continue
        try:
            pid = uuid.UUID(product_id)
        except ValueError:
            continue
        # The move first: it exists once per sale and product
        # (stock_moves_pos_sale_once), so a repeated delivery stops here.
        made = await session.execute(
            text(
                """
                INSERT INTO stock_moves (id, org_id, product_id, product_name, qty_delta, reason, reference, warehouse_id, created_at)
                SELECT gen_random_uuid(), org_id, id, name, ROUND(-(:base + :sold * sales_factor), 3),
                       'pos_sale', :ref, default_warehouse_id, :now
                FROM products WHERE id = :pid AND org_id = :org AND track_inventory
                ON CONFLICT (org_id, product_id, reference) WHERE reason = 'pos_sale' AND reference <> '' DO NOTHING
                RETURNING qty_delta
                """
            ),
            {"base": totals["base"], "sold": totals["sold"], "ref": reference, "now": now, "pid": pid, "org": org_id},
        )
        delta = made.scalar()
        if delta is None:
            continue  # not a tracked product of this org, or already applied
        # Atomic: two tills selling the same item at once both count.
        await session.execute(
            text("UPDATE products SET on_hand_qty = on_hand_qty + :delta, updated_at = :now WHERE id = :pid AND org_id = :org"),
            {"delta": delta, "now": now, "pid": pid, "org": org_id},
        )
    await session.commit()


@suppliers_router.get("", response_model=list[SupplierOut])
async def list_suppliers(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Supplier).where(Supplier.org_id == _org(principal)).order_by(Supplier.name)
    )
    return rows.scalars().all()


@suppliers_router.post("", response_model=SupplierOut, status_code=201)
async def create_supplier(
    body: SupplierCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    supplier = Supplier(org_id=_org(principal), created_at=datetime.now(UTC), **body.model_dump())
    session.add(supplier)
    await session.commit()
    await session.refresh(supplier)
    return supplier


async def _get_owned_po(session: AsyncSession, principal: Principal, po_id: uuid.UUID) -> PurchaseOrder:
    po = await session.get(PurchaseOrder, po_id)
    if po is None or str(po.org_id) != principal.org_id:
        raise HTTPException(404, "purchase order not found")
    return po


@purchase_orders_router.get("", response_model=list[PurchaseOrderOut])
async def list_purchase_orders(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(PurchaseOrder).where(PurchaseOrder.org_id == _org(principal)).order_by(PurchaseOrder.created_at.desc())
    )
    return [PurchaseOrderOut.from_model(po) for po in rows.scalars().all()]


@purchase_orders_router.post("", response_model=PurchaseOrderOut, status_code=201)
async def create_purchase_order(
    body: PurchaseOrderCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    now = datetime.now(UTC)
    po = PurchaseOrder(
        org_id=_org(principal),
        supplier_id=body.supplier_id,
        supplier_invoice_no=body.supplier_invoice_no.strip(),
        supplier_invoice_date=body.supplier_invoice_date,
        number=f"PO-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        created_at=now,
        updated_at=now,
    )
    session.add(po)
    await session.flush()
    for line in body.lines:
        uom_id, uom_name, factor = await purchase_unit_for(session, _org(principal), line.product_id, line.uom_id, line.uom_factor)
        session.add(
            PurchaseOrderLine(
                org_id=_org(principal),
                purchase_order_id=po.id,
                product_id=line.product_id,
                description=line.description,
                quantity=line.quantity,
                uom_id=uom_id,
                uom_name=uom_name,
                uom_factor=factor,
                unit_cost_cents=line.unit_cost_cents,
                tax_code=line.tax_code,
            )
        )
    await session.commit()
    await session.refresh(po, attribute_names=["lines"])
    return PurchaseOrderOut.from_model(po)


@purchase_orders_router.get("/{po_id}", response_model=PurchaseOrderOut)
async def get_purchase_order(
    po_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    po = await _get_owned_po(session, principal, po_id)
    return PurchaseOrderOut.from_model(po)


@purchase_orders_router.patch("/{po_id}/status", response_model=PurchaseOrderOut)
async def set_purchase_order_status(
    po_id: uuid.UUID,
    body: PurchaseOrderStatusUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.status not in PURCHASE_ORDER_STATUSES:
        raise HTTPException(422, f"status must be one of {PURCHASE_ORDER_STATUSES}")
    po = await _get_owned_po(session, principal, po_id)
    previous_status = po.status
    po.status = body.status
    po.updated_at = datetime.now(UTC)
    if body.supplier_invoice_no is not None:
        po.supplier_invoice_no = body.supplier_invoice_no.strip()
    if body.supplier_invoice_date is not None:
        po.supplier_invoice_date = body.supplier_invoice_date

    # Receiving a PO is the one side effect: each line carrying a
    # product_id bumps that product's on_hand_qty and writes a StockMove,
    # the same ledger-plus-cache shape adjust_stock and pos_sale_recorded
    # already use. Only fires on the transition into "received" so
    # re-saving an already-received PO never double-counts stock.
    if previous_status != "received" and body.status == "received":
        for line in po.lines:
            if not line.product_id:
                continue
            product = await session.get(Product, line.product_id)
            if product is None or str(product.org_id) != principal.org_id or not product.track_inventory:
                continue
            # Ordered in cartons of 24: 2 cartons add 48 base units.
            base_qty = (Decimal(line.quantity) * Decimal(line.uom_factor)).quantize(Decimal("0.001"))
            product.on_hand_qty = Decimal(product.on_hand_qty) + base_qty
            product.updated_at = po.updated_at
            session.add(
                StockMove(
                    org_id=_org(principal),
                    product_id=product.id,
                    product_name=product.name,
                    qty_delta=base_qty,
                    reason="received",
                    reference=po.number,
                    warehouse_id=product.default_warehouse_id,
                    created_at=po.updated_at,
                )
            )

    received_now = previous_status != "received" and body.status == "received"
    if received_now:
        po.received_at = po.updated_at
        await price_purchase_vat(session, principal.org_id, po)
    await session.commit()
    await session.refresh(po, attribute_names=["lines"])
    if received_now:
        await publish_purchase_received(session, principal.org_id, po)
    return PurchaseOrderOut.from_model(po)


@purchase_orders_router.post("/from-product/{product_id}", response_model=PurchaseOrderOut, status_code=201)
async def create_purchase_order_from_product(
    product_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    """The "Create purchase order" action on a low-stock product (see
    web/src/apps/inventory/CreatePurchaseOrderPanel.tsx) -- a one-line
    draft PO that restocks to double the reorder point, left in "draft"
    for a human to pick a supplier and actually send."""
    product = await _get_owned(session, principal, product_id)
    now = datetime.now(UTC)
    # Enough purchase units to reach twice the reorder point (base units).
    short = Decimal(product.reorder_point) * 2 - Decimal(product.on_hand_qty)
    per_unit = Decimal(product.purchase_factor or 1)
    quantity = max(math.ceil(short / per_unit) if short > 0 else 1, 1)
    uom_id, uom_name, factor = await purchase_unit_for(session, _org(principal), product.id, None, None)
    po = PurchaseOrder(
        org_id=_org(principal),
        number=f"PO-{now:%Y%m}-{uuid.uuid4().hex[:6].upper()}",
        status="draft",
        created_at=now,
        updated_at=now,
    )
    session.add(po)
    await session.flush()
    session.add(
        PurchaseOrderLine(
            org_id=_org(principal),
            purchase_order_id=po.id,
            product_id=product.id,
            description=product.name,
            quantity=quantity,
            uom_id=uom_id,
            uom_name=uom_name,
            uom_factor=factor,
            # cost_cents is per base unit; the line is per purchase unit.
            unit_cost_cents=int((Decimal(product.cost_cents) * factor).to_integral_value()),
        )
    )
    await session.commit()
    await session.refresh(po, attribute_names=["lines"])
    return PurchaseOrderOut.from_model(po)


@warehouses_router.get("", response_model=list[WarehouseOut])
async def list_warehouses(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(select(Warehouse).where(Warehouse.org_id == _org(principal)).order_by(Warehouse.name))
    return rows.scalars().all()


@warehouses_router.post("", response_model=WarehouseOut, status_code=201)
async def create_warehouse(
    body: WarehouseCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    warehouse = Warehouse(org_id=_org(principal), created_at=datetime.now(UTC), **body.model_dump())
    session.add(warehouse)
    await session.commit()
    await session.refresh(warehouse)
    return warehouse


app.include_router(products_router)
app.include_router(etims_router)
app.include_router(purchases_router)
# Stock levels are not importable: on_hand_qty moves only through stock
# moves. Import the catalogue, then count stock with adjustments.
app.include_router(
    import_router(
        [
            ImportTarget(
                "product",
                "Products",
                "products",
                (
                    ImportField("name", "Name", required=True),
                    ImportField("sku", "SKU"),
                    ImportField("barcode", "Barcode"),
                    ImportField("category", "Category"),
                    ImportField("price_cents", "Price", "cents"),
                    ImportField("cost_cents", "Cost", "cents"),
                    ImportField("reorder_point", "Reorder point", "int"),
                    ImportField("track_inventory", "Track stock", "bool"),
                ),
            ),
            ImportTarget(
                "supplier",
                "Suppliers",
                "suppliers",
                (
                    ImportField("name", "Name", required=True),
                    ImportField("email", "Email", "email"),
                    ImportField("phone", "Phone", "phone"),
                ),
            ),
        ]
    )
)
app.include_router(moves_router)
app.include_router(suppliers_router)
app.include_router(purchase_orders_router)
app.include_router(warehouses_router)
app.include_router(uoms_router)
app.include_router(webhooks_router)
