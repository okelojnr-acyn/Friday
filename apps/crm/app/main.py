import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_org_session,
    publish_event,
    resource,
)

from .models import Opportunity, PRIORITIES
from .schemas import OpportunityCreate, OpportunityOut, OpportunityUpdate, STAGES

resource(
    ResourceSpec(
        name="opportunity",
        app="crm",
        label="Opportunity",
        label_plural="Opportunities",
        views=("list", "kanban", "form"),
        kanban_group_by="stage",
        search_fields=("contact_name", "company"),
        fields=(
            FieldSpec("contact_name", "Contact", "text", required=True),
            FieldSpec("company", "Company", "text"),
            FieldSpec("contact_email", "Email", "email"),
            FieldSpec("stage", "Stage", "select", options=STAGES, required=True),
            FieldSpec("priority", "Priority", "select", options=PRIORITIES, required=True),
            FieldSpec("value_cents", "Value", "currency"),
            FieldSpec("currency", "Currency", "text"),
            FieldSpec("next_step_at", "Next step", "date"),
            FieldSpec("notes", "Notes", "textarea", list_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

app = create_app("friday-crm")
router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("", response_model=list[OpportunityOut])
async def list_opportunities(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Opportunity).where(Opportunity.org_id == uuid.UUID(principal.org_id)).order_by(Opportunity.created_at.desc())
    )
    return rows.scalars().all()


@router.post("", response_model=OpportunityOut, status_code=201)
async def create_opportunity(
    body: OpportunityCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    if body.stage not in STAGES:
        raise HTTPException(422, f"stage must be one of {STAGES}")
    if body.priority not in PRIORITIES:
        raise HTTPException(422, f"priority must be one of {PRIORITIES}")
    now = datetime.now(UTC)
    opp = Opportunity(
        org_id=uuid.UUID(principal.org_id),
        created_by=uuid.UUID(principal.user_id),
        created_at=now,
        updated_at=now,
        **body.model_dump(),
    )
    session.add(opp)
    await session.commit()
    await session.refresh(opp)
    return opp


async def _get_owned(session: AsyncSession, principal: Principal, opp_id: uuid.UUID) -> Opportunity:
    opp = await session.get(Opportunity, opp_id)
    if opp is None or str(opp.org_id) != principal.org_id:
        raise HTTPException(404, "opportunity not found")
    return opp


@router.get("/{opp_id}", response_model=OpportunityOut)
async def get_opportunity(
    opp_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    return await _get_owned(session, principal, opp_id)


@router.patch("/{opp_id}", response_model=OpportunityOut)
async def update_opportunity(
    opp_id: uuid.UUID,
    body: OpportunityUpdate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    opp = await _get_owned(session, principal, opp_id)
    changes = body.model_dump(exclude_unset=True)
    if "stage" in changes and changes["stage"] not in STAGES:
        raise HTTPException(422, f"stage must be one of {STAGES}")
    if "priority" in changes and changes["priority"] not in PRIORITIES:
        raise HTTPException(422, f"priority must be one of {PRIORITIES}")

    previous_stage = opp.stage
    for field_name, value in changes.items():
        setattr(opp, field_name, value)
    opp.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(opp)

    # The one cross-app integration point in the MVP: winning an
    # opportunity gives Invoicing enough to draft an invoice. See
    # kernel/internal/gateway/events.go for where this gets routed.
    if previous_stage != "won" and opp.stage == "won":
        await publish_event(
            "crm.opportunity.won",
            principal.org_id,
            {
                "opportunity_id": str(opp.id),
                "contact_name": opp.contact_name,
                "contact_email": opp.contact_email,
                "company": opp.company,
                "value_cents": opp.value_cents,
                "currency": opp.currency,
            },
        )

    return opp


@router.delete("/{opp_id}", status_code=204)
async def delete_opportunity(
    opp_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    opp = await _get_owned(session, principal, opp_id)
    await session.delete(opp)
    await session.commit()


app.include_router(router)
