"""Stripe payment adapter -- code-ready. Needs a `secret_key`
(`sk_test_...` / `sk_live_...`) in the org's stored config (Settings ->
Integrations -> Stripe); `webhook_secret` (`whsec_...`) is optional but
required for `verify_webhook_signature` to do anything. Talks to Stripe's
REST API directly over `httpx` rather than the `stripe` SDK, consistent
with this package's "no dependency we don't need" posture. See
INTEGRATIONS.md#stripe for the full connect flow, and
`apps/invoicing/app/webhooks.py` for the one real call site (pay-with-card
on an invoice).
"""

import hashlib
import hmac

import httpx

from .base import PaymentProvider

STRIPE_API_BASE = "https://api.stripe.com/v1"


class StripeProvider(PaymentProvider):
    def __init__(self, config: dict):
        self.secret_key = config["secret_key"]
        self.webhook_secret = config.get("webhook_secret", "")

    async def create_payment_intent(self, amount_cents: int, currency: str, metadata: dict) -> dict:
        data: dict[str, str] = {
            "amount": str(amount_cents),
            "currency": currency.lower(),
            "automatic_payment_methods[enabled]": "true",
        }
        for key, value in metadata.items():
            data[f"metadata[{key}]"] = str(value)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{STRIPE_API_BASE}/payment_intents", data=data, auth=(self.secret_key, "")
            )
            resp.raise_for_status()
            return resp.json()

    async def refund(self, payment_id: str, amount_cents: int | None = None) -> dict:
        data: dict[str, str] = {"payment_intent": payment_id}
        if amount_cents is not None:
            data["amount"] = str(amount_cents)
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{STRIPE_API_BASE}/refunds", data=data, auth=(self.secret_key, ""))
            resp.raise_for_status()
            return resp.json()

    def verify_webhook_signature(self, payload: bytes, sig_header: str) -> bool:
        """Stripe's `Stripe-Signature` header is `t=<timestamp>,v1=<hmac>,...`
        -- see https://stripe.com/docs/webhooks/signatures. Always verify
        before trusting a webhook body; this is what stops anyone who
        knows an invoice's PaymentIntent id from POSTing a fake
        `payment_intent.succeeded` straight to the webhook route."""
        if not self.webhook_secret or not sig_header:
            return False
        parts = dict(p.split("=", 1) for p in sig_header.split(",") if "=" in p)
        timestamp, signature = parts.get("t"), parts.get("v1")
        if not timestamp or not signature:
            return False
        signed_payload = f"{timestamp}.".encode() + payload
        expected = hmac.new(self.webhook_secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
