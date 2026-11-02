import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProductCreate(BaseModel):
    name: str = Field(min_length=1)
    sku: str = ""
    barcode: str = ""
    price_cents: int = 0
    cost_cents: int = 0
    on_hand_qty: int = 0
    track_inventory: bool = True


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    barcode: str | None = None
    price_cents: int | None = None
    cost_cents: int | None = None
    track_inventory: bool | None = None


class ProductOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    sku: str
    barcode: str
    price_cents: int
    cost_cents: int
    on_hand_qty: int
    track_inventory: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


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
