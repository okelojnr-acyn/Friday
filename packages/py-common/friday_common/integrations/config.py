import logging

import httpx

from ..settings import get_settings

logger = logging.getLogger("friday.integrations")


async def get_integration_config(org_id: str, provider: str) -> dict:
    """Fetch an org's stored config for one integration provider from the
    kernel's credential store (`core.integration_credentials`, served by
    `kernel/internal/integrations`). Returns `{}` if the org never
    connected that provider -- never raises, so a call site can treat an
    empty dict as "this org hasn't set this up" rather than special-casing
    an exception. Same shared-token pattern as `events.py`'s
    `publish_event`: server-to-server, not a per-request JWT.
    """
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.kernel_internal_url}/integrations/{org_id}/{provider}",
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("failed to fetch integration config %s/%s: %s", org_id, provider, exc)
        return {}
