import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class VehicleCreate(BaseModel):
    name: str = Field(min_length=1)
    plate_number: str = ""
    make: str = ""
    model: str = ""
    year: int | None = None
    vin: str = ""
    fuel_type: str = "gasoline"
    status: str = "active"
    odometer: int = 0
    assigned_driver_name: str = ""


class VehicleUpdate(BaseModel):
    name: str | None = None
    plate_number: str | None = None
    make: str | None = None
    model: str | None = None
    year: int | None = None
    vin: str | None = None
    fuel_type: str | None = None
    status: str | None = None
    odometer: int | None = None
    assigned_driver_name: str | None = None


class VehicleOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    plate_number: str
    make: str
    model: str
    year: int | None
    vin: str
    fuel_type: str
    status: str
    odometer: int
    assigned_driver_name: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DriverCreate(BaseModel):
    name: str = Field(min_length=1)
    email: str = ""
    phone: str = ""
    license_number: str = ""
    license_expires_on: date | None = None
    status: str = "active"


class DriverOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    email: str
    phone: str
    license_number: str
    license_expires_on: date | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MaintenanceLogCreate(BaseModel):
    vehicle_id: uuid.UUID
    service_date: date
    odometer: int = 0
    description: str = Field(min_length=1)
    cost_cents: int = 0
    vendor: str = ""


class MaintenanceLogOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    vehicle_id: uuid.UUID
    service_date: date
    odometer: int
    description: str
    cost_cents: int
    vendor: str

    model_config = {"from_attributes": True}


class FuelLogCreate(BaseModel):
    vehicle_id: uuid.UUID
    fill_date: date
    odometer: int = 0
    quantity: int = Field(gt=0)
    cost_cents: int = 0


class FuelLogOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    vehicle_id: uuid.UUID
    fill_date: date
    odometer: int
    quantity: int
    cost_cents: int

    model_config = {"from_attributes": True}
