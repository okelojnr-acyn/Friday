import logging

import httpx
from fastapi import Header, HTTPException, status

from .settings import get_settings

logger = logging.getLogger("friday.events")


class EventIn:
    """Shape of an event the kernel forwards to a subscriber's webhook."""

    def __init__(self, type: str, org_id: str, payload: dict):
        self.type = type
        self.org_id = org_id
        self.payload = payload


def require_kernel_token(authorization: str | None = Header(default=None)) -> None:
    """Dependency for an app's inbound webhook routes: verifies the call
    actually came from the kernel's event dispatcher, using the same
    shared token `publish_event` sends out with."""
    settings = get_settings()
    expected = f"Bearer {settings.kernel_events_token}"
    if authorization != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid kernel token")


async def publish_event(event_type: str, org_id: str, payload: dict) -> None:
    """Publish a domain event (e.g. "crm.opportunity.won") to the kernel,
    which fans it out to whichever apps have registered a webhook for it.

    Deliberately a plain HTTP POST, not a message broker. At small-business
    scale a broker is infrastructure you have to run and monitor for no
    benefit; this is the one cross-app integration seam in the whole system
    (see ARCHITECTURE.md), and it's one HTTP call. If you outgrow this,
    swap the kernel's dispatcher for NATS/SQS without touching apps -- they
    only know `publish_event`.
    """
    settings = get_settings()
    body = {"type": event_type, "org_id": org_id, "payload": payload}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.kernel_internal_url}/events",
                json=body,
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        # Event delivery is best-effort: a dropped notification should
        # never fail the request that triggered it.
        logger.warning("failed to publish event %s: %s", event_type, exc)
