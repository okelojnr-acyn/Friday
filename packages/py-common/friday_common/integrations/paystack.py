"""Paystack adapter (https://paystack.com/docs/api), the business's own
keys: the org's stored config holds `secret_key` (`sk_live_...` or
`sk_test_...`). Same trust rule as Friday Host's billing/paystack.go: a
payment counts only after `verify(reference)` says so -- never a webhook
body or a redirect on its own. Call sites: apps/invoicing/app/paystack.py
(POS checkout, invoice pay links, settling) and webhooks.py's
paystack_webhook.
"""

import hashlib
import hmac
import json
from datetime import date, timedelta
from urllib.parse import quote

import httpx

from .base import PaymentProvider

PAYSTACK_API_BASE = "https://api.paystack.co"


class PaystackProvider(PaymentProvider):
    def __init__(self, config: dict):
        self.secret_key = config["secret_key"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.secret_key}"}

    async def create_payment_intent(self, amount_cents: int, currency: str, metadata: dict) -> dict:
        """POST /transaction/initialize. metadata must carry `reference`
        (ours, unique per attempt) and `email` (Paystack requires one); it
        may carry `callback_url` and `channels` (e.g. ["mobile_money"]).
        Returns `{"id": reference, "redirect_url": authorization_url}`.
        Amounts are in the currency's subunit, as Friday's cents are."""
        reference = metadata.get("reference")
        email = metadata.get("email")
        if not reference or not email:
            raise ValueError("Paystack create_payment_intent needs metadata.reference and metadata.email")
        body = {
            "email": email,
            "amount": int(amount_cents),
            "currency": currency.upper(),
            "reference": reference,
            "metadata": {k: v for k, v in metadata.items() if k in ("invoice_id", "org_id", "description")},
        }
        if metadata.get("callback_url"):
            body["callback_url"] = metadata["callback_url"]
        if metadata.get("channels"):
            body["channels"] = metadata["channels"]
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{PAYSTACK_API_BASE}/transaction/initialize", json=body, headers=self._headers())
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get("status"):
            raise RuntimeError(f"Paystack initialize failed: {data.get('message') or resp.status_code}")
        return {"id": reference, "redirect_url": data["data"]["authorization_url"]}

    async def charge_mobile_money(
        self, amount_cents: int, currency: str, email: str, phone: str, provider: str, reference: str
    ) -> dict:
        """POST /charge with mobile_money: Paystack pushes the payment prompt
        (M-Pesa STK) straight to `phone`, no checkout page. Returns
        `{"status", "display_text"}`; the payment still counts only once
        `verify(reference)` says success."""
        body = {
            "email": email,
            "amount": int(amount_cents),
            "currency": currency.upper(),
            "reference": reference,
            "mobile_money": {"phone": phone, "provider": provider},
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{PAYSTACK_API_BASE}/charge", json=body, headers=self._headers())
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get("status"):
            raise RuntimeError(f"Paystack charge failed: {data.get('message') or resp.status_code}")
        d = data.get("data") or {}
        status = str(d.get("status", "")).lower()
        if status == "failed":
            raise RuntimeError(f"Paystack charge failed: {d.get('gateway_response') or d.get('message') or 'declined'}")
        return {"status": status, "display_text": str(d.get("display_text") or "")}

    async def verify(self, reference: str) -> dict:
        """GET /transaction/verify/:reference -- the only answer Friday
        trusts. Returns `{"status", "amount", "currency", "channel"}`;
        status is Paystack's own (success, failed, abandoned, ongoing,
        pending, reversed), "" when Paystack doesn't know the reference."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{PAYSTACK_API_BASE}/transaction/verify/{quote(reference, safe='')}", headers=self._headers()
            )
        if resp.status_code == 404:
            return {"status": "", "amount": 0, "currency": "", "channel": ""}
        resp.raise_for_status()
        d = resp.json().get("data") or {}
        return {
            "status": str(d.get("status", "")).lower(),
            "amount": int(d.get("amount") or 0),
            "currency": str(d.get("currency", "")).upper(),
            "channel": str(d.get("channel", "")).lower(),
        }

    async def create_pay_request(
        self, amount_cents: int, currency: str, *, email: str, name: str, description: str,
        reference: str, due_days: int, metadata: dict,
    ) -> dict:
        """Paystack Payment Request (POST /paymentrequest): Paystack emails
        the customer and shows it "pending" until paid. It needs a Paystack
        customer (POST /customer by email first). Paystack gives no pay URL
        for it, so "url" is ""."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            first, _, last = name.strip().partition(" ")
            c = await client.post(
                f"{PAYSTACK_API_BASE}/customer",
                json={"email": email, "first_name": first, "last_name": last},
                headers=self._headers(),
            )
            cd = c.json() if c.content else {}
            if c.status_code >= 400 or not cd.get("status"):
                raise RuntimeError(f"Paystack customer failed: {cd.get('message') or c.status_code}")
            due = (date.today() + timedelta(days=max(due_days, 0))).isoformat()
            resp = await client.post(
                f"{PAYSTACK_API_BASE}/paymentrequest",
                json={
                    "customer": cd["data"]["customer_code"],
                    "amount": int(amount_cents),
                    "currency": currency.upper(),
                    "due_date": due,
                    "description": description,
                    "send_notification": True,
                    "invoice_number": reference[-20:],
                    "metadata": json.dumps(metadata),
                },
                headers=self._headers(),
            )
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400 or not data.get("status"):
            raise RuntimeError(f"Paystack payment request failed: {data.get('message') or resp.status_code}")
        return {"ref": data["data"]["request_code"], "url": ""}

    async def pay_request_status(self, ref: str) -> dict:
        """GET /paymentrequest/verify/:code. Paid is its `paid` flag (or a
        `paid_at`), not a status string."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{PAYSTACK_API_BASE}/paymentrequest/verify/{quote(ref, safe='')}", headers=self._headers()
            )
        if resp.status_code == 404:
            return {"paid": False, "amount": 0, "currency": ""}
        resp.raise_for_status()
        d = resp.json().get("data") or {}
        paid = bool(d.get("paid") or d.get("paid_at"))
        return {"paid": paid, "amount": int(d.get("amount") or 0) if paid else 0, "currency": str(d.get("currency", "")).upper()}

    async def cancel_pay_request(self, ref: str) -> None:
        """POST /paymentrequest/archive/:code."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{PAYSTACK_API_BASE}/paymentrequest/archive/{quote(ref, safe='')}", headers=self._headers()
            )
        if resp.status_code >= 400 and resp.status_code != 404:
            resp.raise_for_status()

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """`x-paystack-signature` is the hex HMAC-SHA512 of the raw body
        with the secret key. Constant-time compare."""
        if not signature:
            return False
        expected = hmac.new(self.secret_key.encode(), payload, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature.strip().lower())

    async def refund(self, payment_id: str, amount_cents: int | None = None) -> dict:
        """POST /refund for a transaction reference, whole or in part."""
        body: dict = {"transaction": payment_id}
        if amount_cents is not None:
            body["amount"] = int(amount_cents)
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{PAYSTACK_API_BASE}/refund", json=body, headers=self._headers())
        resp.raise_for_status()
        return resp.json()
