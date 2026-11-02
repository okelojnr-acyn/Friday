"""Paystack adapter -- STUB, same `PaymentProvider` interface as the
code-ready `stripe.py`. Paystack's REST API
(https://paystack.com/docs/api) is close enough to Stripe's shape that
`stripe.py` is a near-literal template: Bearer-token auth (`secret_key`
below, a `sk_live_...`/`sk_test_...` key from the Paystack dashboard)
instead of Stripe's Basic-auth-with-empty-password, `POST
/transaction/initialize` instead of `/payment_intents`, `POST /refund`
instead of `/refunds`. Webhook signature verification uses an
`x-paystack-signature` header (HMAC-SHA512 of the raw body with the
secret key) instead of Stripe's `t=...,v1=...` scheme. See
INTEGRATIONS.md#paystack.
"""

from .base import PaymentProvider


class PaystackProvider(PaymentProvider):
    def __init__(self, config: dict):
        self.secret_key = config["secret_key"]

    async def create_payment_intent(self, amount_cents: int, currency: str, metadata: dict) -> dict:
        raise NotImplementedError(
            "Paystack adapter is a stub -- see INTEGRATIONS.md#paystack and this file's docstring"
        )

    async def refund(self, payment_id: str, amount_cents: int | None = None) -> dict:
        raise NotImplementedError(
            "Paystack adapter is a stub -- see INTEGRATIONS.md#paystack and this file's docstring"
        )
