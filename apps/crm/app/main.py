import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from friday_common import (
    FieldSpec,
    Principal,
    ResourceSpec,
    create_app,
    get_current_principal,
    get_integration_config,
    get_org_session,
    publish_event,
    resource,
)
from friday_common.integrations import SlackProvider
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import PRIORITIES, Activity, Opportunity
from .schemas import STAGES, ActivityCreate, ActivityOut, OpportunityCreate, OpportunityOut, OpportunityUpdate

logger = logging.getLogger("friday.crm")

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
            FieldSpec("lost_reason", "Lost reason", "text", list_visible=False),
            FieldSpec("created_at", "Created", "datetime", form_visible=False),
        ),
    )
)

resource(
    ResourceSpec(
        name="activity",
        app="crm",
        label="Activity",
        label_plural="Activities",
        views=("list",),
        search_fields=("body",),
        fields=(
            FieldSpec("opportunity_id", "Opportunity", "reference", reference="crm.opportunity", required=True),
            FieldSpec("body", "Note", "textarea", required=True),
            FieldSpec("created_at", "When", "datetime", form_visible=False),
        ),
    )
)

app = create_app("friday-crm")
router = APIRouter(prefix="/opportunities", tags=["opportunities"])
activities_router = APIRouter(prefix="/activities", tags=["activities"])


async def _notify_slack(org_id: str, text: str) -> None:
    """Best-effort: an org that hasn't connected Slack (the common case)
    just gets no notification, same posture as `publish_event` -- a
    notification failing or being unconfigured must never fail the
    opportunity update that triggered it."""
    config = await get_integration_config(org_id, "slack")
    if not config.get("webhook_url"):
        return
    try:
        await SlackProvider(config).notify(text)
    except Exception as exc:  # noqa: BLE001 -- see docstring, this must never propagate
        logger.warning("slack notify failed: %s", exc)


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
        await _notify_slack(
            principal.org_id,
            f":tada: Won: {opp.contact_name} ({opp.company}) -- {opp.currency} {opp.value_cents / 100:,.2f}",
        )
    elif previous_stage != "lost" and opp.stage == "lost":
        reason = f" -- {opp.lost_reason}" if opp.lost_reason else ""
        await _notify_slack(principal.org_id, f":x: Lost: {opp.contact_name} ({opp.company}){reason}")

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


@activities_router.get("", response_model=list[ActivityOut])
async def list_activities(
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    rows = await session.execute(
        select(Activity).where(Activity.org_id == uuid.UUID(principal.org_id)).order_by(Activity.created_at.desc())
    )
    return rows.scalars().all()


@activities_router.post("", response_model=ActivityOut, status_code=201)
async def create_activity(
    body: ActivityCreate,
    principal: Principal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_org_session),
):
    opp = await session.get(Opportunity, body.opportunity_id)
    if opp is None or str(opp.org_id) != principal.org_id:
        raise HTTPException(404, "opportunity not found")
    activity = Activity(
        org_id=uuid.UUID(principal.org_id),
        opportunity_id=body.opportunity_id,
        body=body.body,
        created_at=datetime.now(UTC),
    )
    session.add(activity)
    await session.commit()
    await session.refresh(activity)
    return activity


app.include_router(router)
app.include_router(activities_router)
