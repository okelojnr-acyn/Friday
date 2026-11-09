"""Pesapal adapter -- code-ready, same `PaymentProvider` interface as
`stripe.py`. Pesapal (https://developer.pesapal.com) is OAuth-token-based
rather than a static secret key: the org's stored config holds a
`consumer_key`/`consumer_secret` pair, exchanged for a short-lived bearer
token (`POST /api/Auth/RequestToken`) before each call. There's no inline
card-element equivalent -- `create_payment_intent` submits a hosted order
(`POST /api/Transactions/SubmitOrderRequest`) and returns a `redirect_url`
the customer completes payment on; the result only becomes known via the
IPN callback registered once per process (`POST /api/URLSetup/RegisterIPN`)
and re-verified with `get_transaction_status` -- never trust the IPN
body's own claimed status, same principle as Stripe's signature check,
just Pesapal's version is "ask the API directly." See
apps/invoicing/app/main.py's pay_with_pesapal and
apps/invoicing/app/webhooks.py's pesapal_webhook for the one real call
site, and INTEGRATIONS.md#pesapal for the admin-facing connect flow.
"""

import time

import httpx

from .base import PaymentProvider

PESAPAL_API_BASE = "https://pay.pesapal.com/v3"

# Per-process caches, keyed by consumer_key -- fine at this scale (see
# stripe.py's module-level STRIPE_API_BASE for the same "no dependency we
# don't need" posture; a token/IPN-id store shared across processes would
# need a real cache, not worth it for how rarely this rotates). Lost on
# restart, which just means the next call re-fetches/re-registers -- both
# are idempotent from Pesapal's side.
_token_cache: dict[str, tuple[str, float]] = {}
_ipn_id_cache: dict[str, str] = {}


class PesapalProvider(PaymentProvider):
    def __init__(self, config: dict):
        self.consumer_key = config["consumer_key"]
        self.consumer_secret = config["consumer_secret"]

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        cached = _token_cache.get(self.consumer_key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        resp = await client.post(
            f"{PESAPAL_API_BASE}/api/Auth/RequestToken",
            json={"consumer_key": self.consumer_key, "consumer_secret": self.consumer_secret},
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("token")
        if not token:
            raise RuntimeError(f"Pesapal RequestToken did not return a token: {data}")
        # Pesapal's own token lifetime is ~5 minutes; cache for 4 to stay
        # safely inside it rather than racing the expiry on a slow request.
        _token_cache[self.consumer_key] = (token, time.monotonic() + 240)
        return token

    async def _ipn_id(self, client: httpx.AsyncClient, token: str, callback_url: str) -> str:
        cached = _ipn_id_cache.get(self.consumer_key)
        if cached:
            return cached
        resp = await client.post(
            f"{PESAPAL_API_BASE}/api/URLSetup/RegisterIPN",
            json={"url": callback_url, "ipn_notification_type": "GET"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp.raise_for_status()
        data = resp.json()
        ipn_id = data.get("ipn_id")
        if not ipn_id:
            raise RuntimeError(f"Pesapal RegisterIPN did not return an ipn_id: {data}")
        _ipn_id_cache[self.consumer_key] = ipn_id
        return ipn_id

    async def create_payment_intent(self, amount_cents: int, currency: str, metadata: dict) -> dict:
        """metadata must carry `merchant_reference` (the opaque id the IPN
        callback will hand back -- see pay_with_pesapal for how it encodes
        org_id into this) and `callback_url` (this deployment's own IPN
        endpoint, registered lazily on first use). Returns `{"id":
        order_tracking_id, "redirect_url": ...}` -- `id` mirrors Stripe's
        PaymentIntent shape so call sites don't need a provider-specific
        field name."""
        merchant_reference = metadata.get("merchant_reference")
        callback_url = metadata.get("callback_url")
        if not merchant_reference or not callback_url:
            raise ValueError("Pesapal create_payment_intent needs metadata.merchant_reference and metadata.callback_url")

        async with httpx.AsyncClient(timeout=15.0) as client:
            token = await self._access_token(client)
            ipn_id = await self._ipn_id(client, token, callback_url)
            resp = await client.post(
                f"{PESAPAL_API_BASE}/api/Transactions/SubmitOrderRequest",
                json={
                    "id": merchant_reference,
                    "currency": currency.upper(),
                    "amount": amount_cents / 100,
                    "description": metadata.get("description", "POS sale"),
                    "callback_url": callback_url,
                    "notification_id": ipn_id,
                    "billing_address": {"email_address": metadata.get("email", "")},
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("error"):
                raise RuntimeError(f"Pesapal SubmitOrderRequest failed: {data['error']}")
            return {"id": data["order_tracking_id"], "redirect_url": data["redirect_url"]}

    async def get_transaction_status(self, order_tracking_id: str) -> str:
        """Returns Pesapal's authoritative payment status
        (payment_status_description, upper-cased: COMPLETED/FAILED/
        INVALID/REVERSED/...) for a given order_tracking_id -- the only
        thing pesapal_webhook trusts, never the IPN callback body itself.
        Not part of the shared `PaymentProvider` ABC since it's Pesapal's
        own two-step confirm model; same precedent as Stripe adding
        `verify_webhook_signature` beyond the ABC's two methods."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            token = await self._access_token(client)
            resp = await client.get(
                f"{PESAPAL_API_BASE}/api/Transactions/GetTransactionStatus",
                params={"orderTrackingId": order_tracking_id},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("payment_status_description", "")).upper()

    async def refund(self, payment_id: str, amount_cents: int | None = None) -> dict:
        async with httpx.AsyncClient(timeout=15.0) as client:
            token = await self._access_token(client)
            body = {"confirmation_code": payment_id, "remarks": "Refund"}
            if amount_cents is not None:
                body["amount"] = amount_cents / 100
            resp = await client.post(
                f"{PESAPAL_API_BASE}/api/Transactions/RefundRequest",
                json=body,
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()
