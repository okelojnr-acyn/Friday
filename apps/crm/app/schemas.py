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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


__all__ = ["OpportunityCreate", "OpportunityUpdate", "OpportunityOut", "STAGES"]
