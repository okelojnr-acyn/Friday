import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


VEHICLE_STATUSES = ("active", "maintenance", "retired")
DRIVER_STATUSES = ("active", "inactive")
FUEL_TYPES = ("gasoline", "diesel", "electric", "hybrid", "other")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    plate_number: Mapped[str] = mapped_column(Text, nullable=False, default="")
    make: Mapped[str] = mapped_column(Text, nullable=False, default="")
    model: Mapped[str] = mapped_column(Text, nullable=False, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vin: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fuel_type: Mapped[str] = mapped_column(String(16), nullable=False, default="gasoline")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    odometer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Free text, same pattern as apps/projects' Task.assignee_email --
    # deliberately not a reference to a driver row (or a cross-app user
    # id), so a vehicle can be "assigned" without the driver needing a
    # Driver record yet, and so this app never takes a hard dependency
    # on exactly how the fleet tracks drivers.
    assigned_driver_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    phone: Mapped[str] = mapped_column(Text, nullable=False, default="")
    license_number: Mapped[str] = mapped_column(Text, nullable=False, default="")
    license_expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MaintenanceLog(Base):
    """One row per service event -- an append-only history, same
    "ledger, not just a mutable field" shape as apps/inventory's
    StockMove. Vehicle.odometer is the fast-path cache of the latest
    reading; this table is where it actually came from."""

    __tablename__ = "maintenance_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    odometer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    vendor: Mapped[str] = mapped_column(Text, nullable=False, default="")


class FuelLog(Base):
    __tablename__ = "fuel_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    fill_date: Mapped[date] = mapped_column(Date, nullable=False)
    odometer: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Volume in whatever unit the fleet uses (liters or gallons) -- not
    # normalized to one unit, same "don't invent a conversion nobody
    # asked for" posture as Inventory's unit_of_measure being optional.
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
