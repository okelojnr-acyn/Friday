import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UnitOfMeasure(Base):
    __tablename__ = "units_of_measure"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    abbreviation: Mapped[str] = mapped_column(Text, nullable=False, default="")
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
    price_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    on_hand_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Cheap equivalent of Odoo's reordering rules: a visible threshold,
    # not a replenishment engine with purchase orders.
    reorder_point: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Some products (services, one-off items) never carry stock -- their
    # on_hand_qty stays meaningless and POS/sales shouldn't decrement it.
    track_inventory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


REASONS = ("manual_adjustment", "pos_sale", "received")


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
    qty_delta: Mapped[int] = mapped_column(Integer, nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


PURCHASE_ORDER_STATUSES = ("draft", "ordered", "received")


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
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    purchase_order: Mapped["PurchaseOrder"] = relationship(back_populates="lines")

    @property
    def total_cost_cents(self) -> int:
        return self.quantity * self.unit_cost_cents
