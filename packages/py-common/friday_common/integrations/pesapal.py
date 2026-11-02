"""Pesapal adapter -- STUB, same `PaymentProvider` interface as the
code-ready `stripe.py`. Pesapal (https://developer.pesapal.com) is
OAuth-token-based rather than a static secret key: the org's stored
config holds a `consumer_key`/`consumer_secret` pair, which the adapter
exchanges for a short-lived bearer token (`POST
/api/Auth/RequestToken`) before each call, then `POST
/api/Transactions/SubmitOrderRequest` to start a payment and `POST
/api/Transactions/RefundRequest` to refund. Token caching (the bearer
token expires) is the one piece of real logic this stub doesn't have yet
-- don't call RequestToken on every request once this is filled in. See
INTEGRATIONS.md#pesapal.
"""

from .base import PaymentProvider


class PesapalProvider(PaymentProvider):
    def __init__(self, config: dict):
        self.consumer_key = config["consumer_key"]
        self.consumer_secret = config["consumer_secret"]

    async def create_payment_intent(self, amount_cents: int, currency: str, metadata: dict) -> dict:
        raise NotImplementedError(
            "Pesapal adapter is a stub -- see INTEGRATIONS.md#pesapal and this file's docstring"
        )

    async def refund(self, payment_id: str, amount_cents: int | None = None) -> dict:
        raise NotImplementedError(
            "Pesapal adapter is a stub -- see INTEGRATIONS.md#pesapal and this file's docstring"
        )
