import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


PROJECT_STATUSES = ("active", "archived")
TASK_STATUSES = ("todo", "in_progress", "done")
TICKET_STATUSES = ("open", "pending", "resolved", "closed")
TICKET_PRIORITIES = ("low", "medium", "high")
TASK_PRIORITIES = TICKET_PRIORITIES


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    # crm.opportunities.id -- by-id-only, no FK across schemas (same
    # convention as minions.employees.user_id), so a won deal can become
    # a project without this app taking a hard dependency on crm's
    # schema. Optional: plenty of projects start with no sales history
    # at all (an internal initiative, a free pilot).
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="todo")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    assignee_email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    requester_email: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # invoicing.customers.id -- same by-id-only convention as
    # Project.opportunity_id above. Optional: plenty of real support
    # requests come in before whoever's asking is a billed customer yet
    # (or never becomes one), so requester_email stays the one field
    # that's always there regardless.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TimeEntry(Base):
    """Minutes logged against a Task -- the one thing "track time" needs
    that a Task's own fields can't express (a task has one status/
    assignee, but many logged sessions over its life). An append-only
    ledger, same shape as Inventory's StockMove: the thing being tracked
    has a fast-path field for its current state and a separate table for
    the history that explains how it got there -- except here nothing on
    Task caches a running total, since no screen needs one yet."""

    __tablename__ = "time_entries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
