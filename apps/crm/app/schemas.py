import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from .models import STAGES


class OpportunityCreate(BaseModel):
    contact_name: str = Field(min_length=1)
    contact_email: str = ""
    company: str = ""
    stage: str = "new"
    priority: str = "medium"
    value_cents: int = 0
    currency: str = "USD"
    notes: str = ""
    next_step_at: datetime | None = None
    lost_reason: str = ""


class OpportunityUpdate(BaseModel):
    contact_name: str | None = None
    contact_email: str | None = None
    company: str | None = None
    stage: str | None = None
    priority: str | None = None
    value_cents: int | None = None
    currency: str | None = None
    notes: str | None = None
    next_step_at: datetime | None = None
    lost_reason: str | None = None


class OpportunityOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    contact_name: str
    contact_email: str
    company: str
    stage: str
    priority: str
    value_cents: int
    currency: str
    notes: str
    next_step_at: datetime | None
    lost_reason: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ActivityCreate(BaseModel):
    opportunity_id: uuid.UUID
    body: str = Field(min_length=1)


class ActivityOut(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    opportunity_id: uuid.UUID
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


__all__ = [
    "STAGES",
    "ActivityCreate",
    "ActivityOut",
    "OpportunityCreate",
    "OpportunityOut",
    "OpportunityUpdate",
]
