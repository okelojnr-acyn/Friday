"""Stripe pay-with-card: PaymentIntent creation (main.py) and the webhook
that actually marks an invoice paid (webhooks.py). Never hits the real
Stripe API -- StripeProvider is monkeypatched with a fake standing in for
the HTTP calls `friday_common/integrations/stripe.py` makes.
"""


async def _invoice_with_balance(client, cents=5000):
    return (
        await client.post(
            "/invoices", json={"lines": [{"description": "Consulting", "quantity": 1, "unit_price_cents": cents}]}
        )
    ).json()


async def test_pay_with_card_requires_connected_stripe(client):
    inv = await _invoice_with_balance(client)
    resp = await client.post(f"/invoices/{inv['id']}/pay-with-card")
    assert resp.status_code == 400


async def test_pay_with_card_rejects_zero_balance(client, monkeypatch):
    async def fake_config(org_id, provider):
        return {"secret_key": "sk_test_123"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)

    inv = (await client.post("/invoices", json={})).json()  # no lines -> zero balance
    resp = await client.post(f"/invoices/{inv['id']}/pay-with-card")
    assert resp.status_code == 400


async def test_pay_with_card_creates_payment_intent_and_stores_id(client, monkeypatch):
    async def fake_config(org_id, provider):
        return {"secret_key": "sk_test_123", "publishable_key": "pk_test_123"}

    class FakeStripe:
        def __init__(self, config):
            self.config = config

        async def create_payment_intent(self, amount_cents, currency, metadata):
            assert amount_cents == 5000
            assert currency == "USD"
            assert "invoice_id" in metadata and "org_id" in metadata
            return {"id": "pi_123", "client_secret": "secret_abc"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.StripeProvider", FakeStripe)

    inv = await _invoice_with_balance(client)
    resp = await client.post(f"/invoices/{inv['id']}/pay-with-card")
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_secret"] == "secret_abc"
    assert body["publishable_key"] == "pk_test_123"


def _event(org_id: str, invoice_id: str, event_type: str = "payment_intent.succeeded", amount_received: int = 5000):
    return {
        "type": event_type,
        "data": {
            "object": {
                "metadata": {"org_id": org_id, "invoice_id": invoice_id},
                "amount_received": amount_received,
            }
        },
    }


class _AlwaysValidSignature:
    def __init__(self, config):
        self.config = config

    def verify_webhook_signature(self, raw_body, sig_header):
        return True


async def test_stripe_webhook_marks_invoice_paid_on_success(client, principal, monkeypatch):
    inv = await _invoice_with_balance(client)

    async def fake_config(org_id, provider):
        assert org_id == principal.org_id
        return {"secret_key": "sk_test_123", "webhook_secret": "whsec_123"}

    monkeypatch.setattr("app.webhooks.get_integration_config", fake_config)
    monkeypatch.setattr("app.webhooks.StripeProvider", _AlwaysValidSignature)

    resp = await client.post(
        "/external/webhooks/stripe",
        json=_event(principal.org_id, inv["id"]),
        headers={"stripe-signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200

    updated = (await client.get(f"/invoices/{inv['id']}")).json()
    assert updated["status"] == "paid"
    assert updated["paid_cents"] == 5000


async def test_stripe_webhook_rejects_invalid_signature(client, principal, monkeypatch):
    inv = await _invoice_with_balance(client)

    async def fake_config(org_id, provider):
        return {"secret_key": "sk_test_123", "webhook_secret": "whsec_123"}

    class _AlwaysInvalidSignature:
        def __init__(self, config):
            pass

        def verify_webhook_signature(self, raw_body, sig_header):
            return False

    monkeypatch.setattr("app.webhooks.get_integration_config", fake_config)
    monkeypatch.setattr("app.webhooks.StripeProvider", _AlwaysInvalidSignature)

    resp = await client.post(
        "/external/webhooks/stripe", json=_event(principal.org_id, inv["id"]), headers={"stripe-signature": "bad"}
    )
    assert resp.status_code == 400

    unchanged = (await client.get(f"/invoices/{inv['id']}")).json()
    assert unchanged["status"] == "draft"


async def test_stripe_webhook_ignores_unrelated_event_types(client, principal, monkeypatch):
    inv = await _invoice_with_balance(client)

    async def fake_config(org_id, provider):
        return {"secret_key": "sk_test_123", "webhook_secret": "whsec_123"}

    monkeypatch.setattr("app.webhooks.get_integration_config", fake_config)
    monkeypatch.setattr("app.webhooks.StripeProvider", _AlwaysValidSignature)

    resp = await client.post(
        "/external/webhooks/stripe",
        json=_event(principal.org_id, inv["id"], event_type="payment_intent.created"),
        headers={"stripe-signature": "t=1,v1=fake"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ignored": "payment_intent.created"}

    unchanged = (await client.get(f"/invoices/{inv['id']}")).json()
    assert unchanged["status"] == "draft"
