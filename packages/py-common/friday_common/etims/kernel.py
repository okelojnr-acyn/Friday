"""An org's eTIMS and tax settings, read from the kernel
(GET /internal/etims/{org_id}, Bearer KERNEL_EVENTS_TOKEN)."""

import logging
import os

import httpx

from ..settings import get_settings

logger = logging.getLogger(__name__)


def automation_on() -> bool:
    """Sending to KRA is allowed on this server (after production checks)."""
    return os.environ.get("ETIMS_AUTOMATION") == "1"


async def get_etims_config(org_id: str) -> dict:
    """{} when the kernel can't be reached; callers then treat the org as
    filing by hand with KRA's default rates."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.kernel_internal_url}/etims/{org_id}",
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("could not read eTIMS settings for %s: %s", org_id, exc)
        return {}
