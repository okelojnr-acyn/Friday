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
import time

import httpx

from .base import PaymentProvider

STRIPE_API_BASE = "https://api.stripe.com/v1"
SIGNATURE_TOLERANCE_SECONDS = 300


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

    async def create_pay_request(
        self, amount_cents: int, currency: str, *, email: str, name: str, description: str,
        reference: str, due_days: int, metadata: dict,
    ) -> dict:
        """A Stripe Invoice sent to the customer (collection_method
        send_invoice): the customer (found by email, else created), the
        invoice carrying our metadata, one item for the amount on it, then
        send (which finalizes). "url" is its hosted_invoice_url."""
        auth = (self.secret_key, "")
        async with httpx.AsyncClient(timeout=15.0) as client:
            found = await client.get(f"{STRIPE_API_BASE}/customers", params={"email": email, "limit": 1}, auth=auth)
            found.raise_for_status()
            existing = found.json().get("data") or []
            if existing:
                customer = existing[0]["id"]
            else:
                made = await client.post(f"{STRIPE_API_BASE}/customers", data={"email": email, "name": name}, auth=auth)
                made.raise_for_status()
                customer = made.json()["id"]
            form = {"customer": customer, "collection_method": "send_invoice", "days_until_due": str(max(due_days, 1)),
                    "description": description}
            form.update({f"metadata[{k}]": str(v) for k, v in metadata.items()})
            inv = await client.post(f"{STRIPE_API_BASE}/invoices", data=form, auth=auth)
            inv.raise_for_status()
            invoice_id = inv.json()["id"]
            item = await client.post(
                f"{STRIPE_API_BASE}/invoiceitems",
                data={"customer": customer, "invoice": invoice_id, "amount": str(int(amount_cents)),
                      "currency": currency.lower(), "description": description},
                auth=auth,
            )
            item.raise_for_status()
            sent = await client.post(f"{STRIPE_API_BASE}/invoices/{invoice_id}/send", auth=auth)
            sent.raise_for_status()
            return {"ref": invoice_id, "url": sent.json().get("hosted_invoice_url") or ""}

    async def pay_request_status(self, ref: str) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{STRIPE_API_BASE}/invoices/{ref}", auth=(self.secret_key, ""))
        if resp.status_code == 404:
            return {"paid": False, "amount": 0, "currency": ""}
        resp.raise_for_status()
        d = resp.json()
        paid = d.get("status") == "paid"
        return {"paid": paid, "amount": int(d.get("amount_paid") or 0) if paid else 0, "currency": str(d.get("currency", "")).upper()}

    async def cancel_pay_request(self, ref: str) -> None:
        """POST /invoices/{id}/void (a finalized, unpaid invoice)."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{STRIPE_API_BASE}/invoices/{ref}/void", auth=(self.secret_key, ""))
        if resp.status_code >= 400 and resp.status_code not in (400, 404):  # 400: already paid or void
            resp.raise_for_status()

    def verify_webhook_signature(self, payload: bytes, sig_header: str) -> bool:
        """Stripe's `Stripe-Signature` header is `t=<timestamp>,v1=<hmac>,...`
        -- see https://stripe.com/docs/webhooks/signatures. Always verify
        before trusting a webhook body; this is what stops anyone who
        knows an invoice's PaymentIntent id from POSTing a fake
        `payment_intent.succeeded` straight to the webhook route."""
        if not self.webhook_secret or not sig_header:
            return False
        pairs = [p.strip().split("=", 1) for p in sig_header.split(",") if "=" in p]
        timestamp = next((v for k, v in pairs if k == "t"), "")
        # Several v1 values while the business rolls its secret: any may match.
        signatures = [v for k, v in pairs if k == "v1"]
        if not timestamp.isdigit() or not signatures:
            return False
        # A signed event older than Stripe's own 5-minute tolerance is a replay.
        if abs(time.time() - int(timestamp)) > SIGNATURE_TOLERANCE_SECONDS:
            return False
        signed_payload = f"{timestamp}.".encode() + payload
        expected = hmac.new(self.webhook_secret.encode(), signed_payload, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, s) for s in signatures)
