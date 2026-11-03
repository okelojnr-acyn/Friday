import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name: str = Field(min_length=1)
    kind: str = "product"
    sku: str = ""
    barcode: str = ""
    price_cents: int = 0
    cost_cents: int = 0
    on_hand_qty: int = 0
    reorder_point: int = 0
    track_inventory: bool = True


class ProductUpdate(BaseModel):
    name: str | None = None
    kind: str | None = None
    sku: str | None = None
    barcode: str | None = None
    price_cents: int | None = None
    cost_cents: int | None = None
    reorder_point: int | None = None
    track_inventory: bool | None = None


class ProductOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    kind: str
    sku: str
    barcode: str
    price_cents: int
    cost_cents: int
    on_hand_qty: int
    reorder_point: int
    track_inventory: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductBulkCreate(BaseModel):
    products: list[ProductCreate] = Field(min_length=1)


class StockAdjust(BaseModel):
    delta: int
    reason: str = "manual_adjustment"
    reference: str = ""


class StockMoveOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    qty_delta: int
    reason: str
    reference: str
    created_at: datetime

    model_config = {"from_attributes": True}


class SupplierCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str = ""
    phone: str = ""


class SupplierOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    email: str
    phone: str
    created_at: datetime

    model_config = {"from_attributes": True}


class PurchaseOrderLineIn(BaseModel):
    product_id: uuid.UUID | None = None
    description: str = ""
    quantity: int = 1
    unit_cost_cents: int = 0


class PurchaseOrderLineOut(PurchaseOrderLineIn):
    id: uuid.UUID
    total_cost_cents: int

    model_config = {"from_attributes": True}


class PurchaseOrderCreate(BaseModel):
    supplier_id: uuid.UUID | None = None
    lines: list[PurchaseOrderLineIn] = []


class PurchaseOrderStatusUpdate(BaseModel):
    status: str


class PurchaseOrderOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    supplier_id: uuid.UUID | None
    number: str
    status: str
    created_at: datetime
    updated_at: datetime
    lines: list[PurchaseOrderLineOut]
    total_cost_cents: int

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, po) -> "PurchaseOrderOut":
        return cls(
            id=po.id,
            org_id=po.org_id,
            supplier_id=po.supplier_id,
            number=po.number,
            status=po.status,
            created_at=po.created_at,
            updated_at=po.updated_at,
            lines=[
                PurchaseOrderLineOut(
                    id=line.id,
                    product_id=line.product_id,
                    description=line.description,
                    quantity=line.quantity,
                    unit_cost_cents=line.unit_cost_cents,
                    total_cost_cents=line.total_cost_cents,
                )
                for line in po.lines
            ],
            total_cost_cents=sum(line.total_cost_cents for line in po.lines),
        )
