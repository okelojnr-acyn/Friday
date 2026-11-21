import uuid
from datetime import date, datetime
from decimal import Decimal

from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer


def _qty_json(d: Decimal) -> int | float:
    """Quantities go out as numbers: whole ones as integers (what every
    caller read before 0012), fractions (0.5 kg) as decimals."""
    d = Decimal(d)
    return int(d) if d == d.to_integral_value() else float(d)


# A quantity or a unit factor: up to three (factors six) decimals.
Qty = Annotated[Decimal, PlainSerializer(_qty_json, return_type=int | float, when_used="json")]


class ProductCreate(BaseModel):
    name: str = Field(min_length=1)
    kind: str = "product"
    sku: str = ""
    barcode: str = ""
    category: str = ""
    variant_of: uuid.UUID | None = None
    variant_name: str = ""
    price_cents: int = 0
    cost_cents: int = 0
    on_hand_qty: Qty = Decimal(0)
    reorder_point: Qty = Decimal(0)
    track_inventory: bool = True
    default_warehouse_id: uuid.UUID | None = None
    uom_id: uuid.UUID | None = None
    uom_conversion_factor: Decimal = Decimal(1)
    valuation_method: str = "standard"
    base_uom_id: uuid.UUID | None = None
    purchase_uom_id: uuid.UUID | None = None
    purchase_factor: Qty | None = None
    sales_uom_id: uuid.UUID | None = None
    sales_factor: Qty | None = None
    tax_code: str = Field(default="", pattern="^[A-E]?$")
    etims_item_class: str = Field(default="", pattern="^[0-9]{0,10}$")
    etims_packaging_unit: str = Field(default="NT", pattern="^[A-Z0-9]{1,5}$")


class ProductUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    sku: str | None = None
    barcode: str | None = None
    category: str | None = None
    variant_of: uuid.UUID | None = None
    variant_name: str | None = None
    price_cents: int | None = None
    cost_cents: int | None = None
    reorder_point: Qty | None = None
    track_inventory: bool | None = None
    default_warehouse_id: uuid.UUID | None = None
    uom_id: uuid.UUID | None = None
    uom_conversion_factor: Decimal | None = None
    valuation_method: str | None = None
    base_uom_id: uuid.UUID | None = None
    purchase_uom_id: uuid.UUID | None = None
    purchase_factor: Qty | None = None
    sales_uom_id: uuid.UUID | None = None
    sales_factor: Qty | None = None
    tax_code: str | None = Field(default=None, pattern="^[A-E]?$")
    etims_item_class: str | None = Field(default=None, pattern="^[0-9]{0,10}$")
    etims_packaging_unit: str | None = Field(default=None, pattern="^[A-Z0-9]{1,5}$")


class ProductOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    kind: str
    sku: str
    barcode: str
    category: str = ""
    image_sha: str = ""
    variant_of: uuid.UUID | None = None
    variant_name: str = ""
    price_cents: int
    cost_cents: int
    on_hand_qty: Qty
    reorder_point: Qty
    track_inventory: bool
    default_warehouse_id: uuid.UUID | None
    uom_id: uuid.UUID | None
    uom_conversion_factor: Decimal
    valuation_method: str
    base_uom_id: uuid.UUID | None = None
    purchase_uom_id: uuid.UUID | None = None
    purchase_factor: Qty = Decimal(1)
    sales_uom_id: uuid.UUID | None = None
    sales_factor: Qty = Decimal(1)
    tax_code: str = ""
    etims_item_class: str = ""
    etims_packaging_unit: str = "NT"
    etims_item_code: str = ""
    etims_registered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WarehouseCreate(BaseModel):
    name: str = Field(min_length=1)
    code: str = ""
    address: str = ""
    is_default: bool = False


class WarehouseOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    code: str
    address: str
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class UnitOfMeasureCreate(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    abbreviation: str = Field(default="", max_length=10)
    category: str = "unit"
    # None: a pack whose size each product sets.
    ratio: Decimal | None = None
    etims_code: str = Field(default="", max_length=5)


class UnitOfMeasurePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    abbreviation: str | None = Field(default=None, max_length=10)
    active: bool | None = None
    ratio: Decimal | None = None
    etims_code: str | None = Field(default=None, max_length=5)


class UnitOfMeasureOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    abbreviation: str
    code: str = ""
    category: str = "unit"
    ratio: Qty | None = None
    etims_code: str = ""
    active: bool = True
    products_using: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class ProductBulkCreate(BaseModel):
    products: list[ProductCreate] = Field(min_length=1)


class StockAdjust(BaseModel):
    # In the product's base unit.
    delta: Qty
    reason: str = "manual_adjustment"
    reference: str = ""
    warehouse_id: uuid.UUID | None = None


class StockMoveOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    qty_delta: Qty
    reason: str
    reference: str
    warehouse_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str = ""
    phone: str = ""
    kra_pin: str = Field(default="", max_length=20)


class SupplierOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    email: str
    phone: str
    kra_pin: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class PurchaseOrderLineIn(BaseModel):
    product_id: uuid.UUID | None = None
    description: str = ""
    quantity: Qty = Decimal(1)
    # The unit the line is ordered in; left out, the product's purchase unit.
    uom_id: uuid.UUID | None = None
    # Base units in one of that unit; set from the product when left out.
    uom_factor: Qty | None = None
    # Before VAT.
    unit_cost_cents: int = 0
    tax_code: str = Field(default="", pattern="^[A-E]?$")


class PurchaseOrderLineOut(PurchaseOrderLineIn):
    id: uuid.UUID
    uom_name: str = ""
    vat_cents: int = 0
    total_cost_cents: int

    model_config = {"from_attributes": True}


class PurchaseOrderCreate(BaseModel):
    supplier_id: uuid.UUID | None = None
    supplier_invoice_no: str = Field(default="", max_length=60)
    supplier_invoice_date: date | None = None
    lines: list[PurchaseOrderLineIn] = []


class PurchaseOrderPay(BaseModel):
    # cash, mpesa, bank_transfer, card, ... (Accounting maps each to an account)
    method: str = Field(min_length=1, max_length=30)
    reference: str = Field(default="", max_length=80)


class PurchaseOrderStatusUpdate(BaseModel):
    status: str
    # Given when receiving: the supplier's invoice that came with the goods.
    supplier_invoice_no: str | None = Field(default=None, max_length=60)
    supplier_invoice_date: date | None = None


class PurchaseOrderOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    supplier_id: uuid.UUID | None
    number: str
    status: str
    supplier_invoice_no: str = ""
    supplier_invoice_date: date | None = None
    received_at: datetime | None = None
    paid_at: datetime | None = None
    paid_method: str = ""
    paid_reference: str = ""
    created_at: datetime
    updated_at: datetime
    lines: list[PurchaseOrderLineOut]
    total_cost_cents: int
    # Cost plus VAT: what the supplier is owed once the goods are in.
    total_due_cents: int = 0

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, po) -> "PurchaseOrderOut":
        return cls(
            id=po.id,
            org_id=po.org_id,
            supplier_id=po.supplier_id,
            number=po.number,
            status=po.status,
            supplier_invoice_no=po.supplier_invoice_no,
            supplier_invoice_date=po.supplier_invoice_date,
            received_at=po.received_at,
            paid_at=po.paid_at,
            paid_method=po.paid_method,
            paid_reference=po.paid_reference,
            created_at=po.created_at,
            updated_at=po.updated_at,
            lines=[
                PurchaseOrderLineOut(
                    id=line.id,
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    uom_id=line.uom_id,
                    uom_name=line.uom_name,
                    uom_factor=line.uom_factor,
                    unit_cost_cents=line.unit_cost_cents,
                    tax_code=line.tax_code,
                    vat_cents=line.vat_cents,
                    total_cost_cents=line.total_cost_cents,
                )
                for line in po.lines
            ],
            total_cost_cents=sum(line.total_cost_cents for line in po.lines),
            total_due_cents=sum(line.total_cost_cents + line.vat_cents for line in po.lines),
        )
