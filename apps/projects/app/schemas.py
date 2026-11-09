import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
    description: str = ""
    status: str = "active"
    opportunity_id: uuid.UUID | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    opportunity_id: uuid.UUID | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    description: str
    status: str
    opportunity_id: uuid.UUID | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    project_id: uuid.UUID | None = None
    title: str = Field(min_length=1)
    description: str = ""
    status: str = "todo"
    priority: str = "medium"
    assignee_email: str = ""
    due_at: datetime | None = None


class TaskUpdate(BaseModel):
    project_id: uuid.UUID | None = None
    title: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    assignee_email: str | None = None
    due_at: datetime | None = None


class TaskOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    project_id: uuid.UUID | None
    title: str
    description: str
    status: str
    priority: str
    assignee_email: str
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TicketCreate(BaseModel):
    subject: str = Field(min_length=1)
    description: str = ""
    status: str = "open"
    priority: str = "medium"
    requester_email: str = ""
    customer_id: uuid.UUID | None = None
    due_at: datetime | None = None


class TicketUpdate(BaseModel):
    subject: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    requester_email: str | None = None
    customer_id: uuid.UUID | None = None
    due_at: datetime | None = None


class TicketOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    subject: str
    description: str
    status: str
    priority: str
    requester_email: str
    customer_id: uuid.UUID | None
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TimeEntryCreate(BaseModel):
    task_id: uuid.UUID
    minutes: int = Field(gt=0)
    note: str = ""


class TimeEntryOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    task_id: uuid.UUID
    minutes: int
    note: str
    created_at: datetime

    model_config = {"from_attributes": True}
