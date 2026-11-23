"""Where this Friday is reachable, as the kernel tells each app on every
request (X-Friday-Public-URL, X-Friday-Web-URL), so payment providers get
webhook and return URLs on whatever domain Friday runs, with no setting
per app. The kernel sets the headers itself; apps are only reachable
through it.

Also: passing Paystack events on to the business's other systems on the
same Paystack account (Paystack allows one webhook URL per account; Stripe
allows several, Pesapal registers one per order), only to public https
addresses.
"""

import asyncio
import ipaddress
import logging
import socket
from contextvars import ContextVar
from urllib.parse import urlsplit

import httpx

from .settings import get_settings

logger = logging.getLogger(__name__)

_kernel_url: ContextVar[str] = ContextVar("friday_public_kernel_url", default="")
_web_url: ContextVar[str] = ContextVar("friday_public_web_url", default="")


class PublicURLMiddleware:
    """Pure ASGI: copies the kernel's headers into context for this request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        k = _kernel_url.set(headers.get(b"x-friday-public-url", b"").decode("latin-1"))
        w = _web_url.set(headers.get(b"x-friday-web-url", b"").decode("latin-1"))
        try:
            await self.app(scope, receive, send)
        finally:
            _kernel_url.reset(k)
            _web_url.reset(w)


def kernel_url() -> str:
    """This Friday's API address; APP_PUBLIC_URL for an app reached directly."""
    return (_kernel_url.get() or get_settings().app_public_url).rstrip("/")


def web_url() -> str:
    return _web_url.get().rstrip("/")


def webhook_url(provider: str) -> str:
    """Where `provider` should send its events: <kernel>/external/webhooks/<provider>."""
    base = kernel_url()
    return f"{base}/external/webhooks/{provider}" if base else ""


def paid_page() -> str:
    """Where a customer lands after paying a link or checkout: a plain
    "payment received" page on this Friday, not the provider account's default."""
    base = web_url()
    return f"{base}/paid" if base else ""


def forward_targets(config: dict) -> list[str]:
    """The provider config's `forward_to` (comma or newline separated)."""
    raw = str(config.get("forward_to") or "")
    return [u.strip() for u in raw.replace("\n", ",").split(",") if u.strip()]


async def public_https(url: str) -> bool:
    """https, and every address the host resolves to is public: a business
    admin can't make Friday call into its own network."""
    # shortcut: checked at resolve time, then httpx resolves again (DNS rebinding window); pin the address if this is ever abused.
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return False
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(parts.hostname, parts.port or 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    addrs = {ipaddress.ip_address(info[4][0]) for info in infos}
    return bool(addrs) and all(a.is_global for a in addrs)


async def forward_event(urls: list[str], method: str, body: bytes, headers: dict[str, str], query: str = "") -> None:
    """Sends a verified provider event, unchanged, to each url (up to 3
    tries). Runs in the background; a failure is logged, never raised."""
    for url in urls:
        if not await public_https(url):
            logger.warning("forward: skipped %s (not a public https address)", url)
            continue
        target = f"{url}{'&' if '?' in url else '?'}{query}" if query else url
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                    resp = await client.request(method, target, content=body, headers=headers)
                if resp.status_code < 500:
                    break
            except httpx.HTTPError as exc:
                logger.warning("forward to %s: %s", url, exc)
            await asyncio.sleep(2 * (attempt + 1))


def forward_in_background(urls: list[str], method: str, body: bytes, headers: dict[str, str]) -> None:
    if urls:
        asyncio.get_running_loop().create_task(forward_event(urls, method, body, headers))
