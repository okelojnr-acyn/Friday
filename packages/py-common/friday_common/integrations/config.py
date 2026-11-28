import logging
import time

import httpx

from ..settings import get_settings

logger = logging.getLogger("friday.integrations")

# A connected provider's config is reused this long per process, so a busy
# till or webhook doesn't ask the kernel on every call. A key changed in
# Apps & integrations reaches each app within this time.
CACHE_SECONDS = 60
_cache: dict[tuple[str, str], tuple[float, dict]] = {}


class IntegrationConfigUnavailable(httpx.HTTPError):
    """The kernel couldn't be asked for a provider's config (restarting,
    network). Not the same as "not connected": the app factory answers it
    with a 503 to retry, and code that already treats an httpx error as a
    provider outage (the till's poll, scheduled checks) keeps doing so."""


async def get_integration_config(org_id: str, provider: str) -> dict:
    """Fetch an org's stored config for one integration provider from the
    kernel's credential store (`core.integration_credentials`, served by
    `kernel/internal/integrations`). Returns `{}` if the org never
    connected that provider, so a call site treats an empty dict as "this
    org hasn't set this up". Raises IntegrationConfigUnavailable when the
    kernel can't be reached, so a blip never looks like "not connected".
    Same shared-token pattern as `events.py`'s `publish_event`:
    server-to-server, not a per-request JWT.
    """
    key = (str(org_id), provider)
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return dict(hit[1])
    config = await _fetch(str(org_id), provider)
    # Only connected configs are kept: one just connected works at once.
    if config:
        _cache[key] = (time.monotonic() + CACHE_SECONDS, config)
    return dict(config)


async def _fetch(org_id: str, provider: str) -> dict:
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.kernel_internal_url}/integrations/{org_id}/{provider}",
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
            resp.raise_for_status()
            config = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("failed to fetch integration config %s/%s: %s", org_id, provider, type(exc).__name__)
        raise IntegrationConfigUnavailable(f"couldn't reach settings for {provider}; try again") from exc
    return config if isinstance(config, dict) else {}


async def forwarding_configs(provider: str) -> list[dict]:
    """Every org's config for `provider` that has `forward_to` set, as
    [{"org_id", "config"}]: who else wants that provider's events (Paystack
    allows one webhook URL per account). [] on any failure."""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.kernel_internal_url}/integrations-forwarding/{provider}",
                headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("failed to fetch forwarding configs for %s: %s", provider, exc)
        return []
