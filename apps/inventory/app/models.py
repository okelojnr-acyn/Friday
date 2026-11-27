import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


PRODUCT_KINDS = ("product", "service")
VALUATION_METHODS = ("standard", "fifo", "average")


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The kernel location it belongs to (0015); None = not set.
    location_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UnitOfMeasure(Base):
    __tablename__ = "units_of_measure"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    abbreviation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 0012: preloaded units carry a code ("kg"); custom ones have "".
    code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str] = mapped_column(Text, nullable=False, default="unit")
    # Size against the category's reference (kg, L, m, piece): 1 g = 0.001.
    # None for a pack (carton, crate) whose size each product sets.
    ratio: Mapped[Decimal | None] = mapped_column(Numeric(20, 10), nullable=True)
    etims_code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Benched units stay on products that use them but leave the pickers.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # "service" (consulting hour, labor, a booking) vs "product" (a
    # physical good with stock). Not just a UI label -- create_product and
    # update_product force track_inventory=False whenever kind="service",
    # so a service never silently starts decrementing a stock count that
    # was never meaningful for it in the first place.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="product")
    sku: Mapped[str] = mapped_column(Text, nullable=False, default="")
    barcode: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Shelf grouping on the till (Groceries, Dairy, ...); free text.
    category: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Changes with the photo (0010); "" = no photo.
    image_sha: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A variant names the product it is a variant of (0010).
    variant_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    variant_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # In the base unit, three decimals (0012).
    on_hand_qty: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    # Cheap equivalent of Odoo's reordering rules: a visible threshold,
    # not a replenishment engine with purchase orders.
    reorder_point: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=0)
    # Some products (services, one-off items) never carry stock -- their
    # on_hand_qty stays meaningless and POS/sales shouldn't decrement it.
    track_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Shown in the online shop (0020).
    sell_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Where new stock lands by default -- on_hand_qty itself stays one
    # global counter for v1, not split per warehouse (see
    # 0005_warehouses_and_uom.sql's comment for the documented path to
    # that). Still real and useful: it's what StockMove.warehouse_id
    # defaults to when a move doesn't specify one.
    default_warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True
    )
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="SET NULL"), nullable=True
    )
    # How many of on_hand_qty's base unit one selling/purchasing unit of
    # this product's uom represents. 1 (the default) means uom is
    # cosmetic -- doesn't change any quantity math.
    uom_conversion_factor: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=1)
    # Field only for v1, not a costing engine -- see
    # 0005_warehouses_and_uom.sql's comment. "standard" (cost_cents
    # as-is) is the only method any code path actually uses today.
    valuation_method: Mapped[str] = mapped_column(String(16), nullable=False, default="standard")
    # Units (0012): stock is kept in base_uom; one purchase unit holds
    # purchase_factor base units, one sales unit sales_factor. price_cents
    # is per sales unit, cost_cents per base unit. uom_id and
    # uom_conversion_factor above are the old single unit, kept readable.
    base_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="SET NULL"), nullable=True
    )
    purchase_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="SET NULL"), nullable=True
    )
    purchase_factor: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False, default=1)
    sales_uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="SET NULL"), nullable=True
    )
    sales_factor: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False, default=1)
    # KRA eTIMS (0011): tax type A-E ("" = the business's default rate),
    # item classification, packaging unit, and the item code eTIMS knows
    # the product by once registered.
    tax_code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    etims_item_class: Mapped[str] = mapped_column(Text, nullable=False, default="")
    etims_packaging_unit: Mapped[str] = mapped_column(Text, nullable=False, default="NT")
    etims_item_code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    etims_registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


REASONS = ("manual_adjustment", "pos_sale", "received", "sale", "write_off", "transfer")


class ProductImage(Base):
    __tablename__ = "product_images"

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StockMove(Base):
    """An append-only ledger of every stock change -- so "how much do we
    have" is always reconstructable and auditable, not just a counter
    someone could silently overwrite. Product.on_hand_qty is the fast-path
    cache; this table is the source of truth for history."""

    __tablename__ = "stock_moves"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    qty_delta: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="manual_adjustment")
    reference: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Which warehouse this move happened at -- defaults to the product's
    # default_warehouse_id when not given explicitly (see main.py's
    # adjust_stock). Nullable: a move predating this column, or for an
    # org that's never set up warehouses, has no location at all.
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phone: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # On the VAT return's purchases schedule (0013).
    kra_pin: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


PURCHASE_ORDER_STATUSES = ("draft", "requested", "approved", "ordered", "received")


class PurchaseOrder(Base):
    """The reorder workflow apps/inventory/migrations/0002's comment
    said this app deliberately didn't have yet. Receiving a PO
    (`status` -> "received") writes a StockMove with reason="received"
    for each line carrying a product_id and bumps that product's
    on_hand_qty -- the exact same ledger-plus-cache shape every other
    stock change in this app already uses (see `adjust_stock` and
    `pos_sale_recorded` in main.py)."""

    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    # A request to buy (0018): who sent it for approval, who decided, why.
    requested_by_user_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_by_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The supplier's own invoice (0013): the VAT return lists it.
    supplier_invoice_no: Mapped[str] = mapped_column(Text, nullable=False, default="")
    supplier_invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Paying the supplier (0014): when, how, and their receipt or M-Pesa code.
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_method: Mapped[str] = mapped_column(Text, nullable=False, default="")
    paid_reference: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The supplier page (0016): "", "acknowledged" or "dispatched", their
    # note, and the sha of the invoice file they added ("" for none).
    supplier_status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    supplier_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    supplier_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invoice_file_sha: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # In the line's own unit (0012); receiving adds quantity x uom_factor.
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=1)
    uom_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("units_of_measure.id", ondelete="SET NULL"), nullable=True
    )
    uom_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    uom_factor: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False, default=1)
    # Before VAT (0013); tax_code A-E ("" = the business default), and the
    # VAT on the line, worked out when the goods are received.
    unit_cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    tax_code: Mapped[str] = mapped_column(Text, nullable=False, default="")
    vat_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")

    @property
    def total_cost_cents(self) -> int:
        return int((Decimal(self.quantity) * self.unit_cost_cents).to_integral_value())


class PoInvoiceFile(Base):
    """The supplier's invoice for a purchase order (0016)."""

    __tablename__ = "po_invoice_files"

    po_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), primary_key=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ShopOrder(Base):
    """An order from the online shop (0019); priced here, never by the page."""

    __tablename__ = "shop_orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    number: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="placed")
    customer_name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False, default="")
    email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fulfilment: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lines: Mapped[list["ShopOrderLine"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class ShopOrderLine(Base):
    __tablename__ = "shop_order_lines"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("shop_orders.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    variant_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit_price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    total_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
