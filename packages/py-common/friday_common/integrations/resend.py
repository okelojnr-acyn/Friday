"""Resend adapter -- code-ready. Needs an `api_key` (`re_...`) in the
org's stored config (Settings -> Integrations -> Resend); `from_email`
is optional and defaults to Resend's own shared sending domain so an org
can send real email the moment they paste a key, before verifying their
own domain. Talks to Resend's REST API directly over `httpx`, consistent
with this package's "no vendor SDK" posture (see stripe.py). See
INTEGRATIONS.md#resend for the full connect flow and the one real call
site (apps/invoicing/app/main.py's set_invoice_status, on "sent").
"""

import httpx

from .base import EmailProvider

RESEND_API_BASE = "https://api.resend.com"


class ResendProvider(EmailProvider):
    def __init__(self, config: dict):
        self.api_key = config["api_key"]
        self.from_email = config.get("from_email", "Friday <onboarding@resend.dev>")

    async def send(self, to: str, subject: str, html: str) -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{RESEND_API_BASE}/emails",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"from": self.from_email, "to": [to], "subject": subject, "html": html},
            )
            resp.raise_for_status()
            return resp.json()
