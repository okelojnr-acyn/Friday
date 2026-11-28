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
        return {"secret_key": "sk_test_123", "publishable_key": "pk_test_123"}

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
                "id": "pi_123",
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


async def test_pay_with_card_needs_the_publishable_key_before_any_payment_intent(client, monkeypatch):
    made = []

    async def fake_config(org_id, provider):
        return {"secret_key": "sk_test_123"}

    class FakeStripe:
        def __init__(self, config):
            pass

        async def create_payment_intent(self, amount_cents, currency, metadata):
            made.append(amount_cents)
            return {"id": "pi_123", "client_secret": "secret_abc"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.StripeProvider", FakeStripe)
    inv = await _invoice_with_balance(client)
    resp = await client.post(f"/invoices/{inv['id']}/pay-with-card")
    assert resp.status_code == 400 and "publishable key" in resp.json()["detail"]
    assert made == []  # no orphan PaymentIntent at Stripe


async def test_a_redelivered_payment_intent_is_recorded_once(client, principal, monkeypatch):
    inv = await _invoice_with_balance(client, cents=10000)

    async def fake_config(org_id, provider):
        return {"secret_key": "sk_test_123", "webhook_secret": "whsec_123"}

    monkeypatch.setattr("app.webhooks.get_integration_config", fake_config)
    monkeypatch.setattr("app.webhooks.StripeProvider", _AlwaysValidSignature)
    event = _event(principal.org_id, inv["id"], amount_received=4000)
    for _ in range(3):  # Stripe delivers at least once and retries
        r = await client.post("/external/webhooks/stripe", json=event, headers={"stripe-signature": "t=1,v1=fake"})
        assert r.status_code == 200
    out = (await client.get(f"/invoices/{inv['id']}")).json()
    assert [p["amount_cents"] for p in out["payments"]] == [4000]
    assert out["status"] != "paid"


def test_stripe_signature_rejects_old_events_and_accepts_any_rotated_secret():
    import hashlib
    import hmac
    import time

    from friday_common.integrations import StripeProvider

    body = b'{"type":"payment_intent.succeeded"}'

    def sign(secret, t):
        return hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()

    provider = StripeProvider({"secret_key": "sk", "webhook_secret": "whsec_new"})
    now = int(time.time())
    assert provider.verify_webhook_signature(body, f"t={now},v1={sign('whsec_new', now)}")
    # During a secret roll Stripe signs with both: either may be ours.
    assert provider.verify_webhook_signature(body, f"t={now},v1={sign('whsec_old', now)},v1={sign('whsec_new', now)}")
    old = now - 301  # past Stripe's 5-minute tolerance: a replay
    assert not provider.verify_webhook_signature(body, f"t={old},v1={sign('whsec_new', old)}")
    assert not provider.verify_webhook_signature(body, f"t={now},v1={sign('whsec_other', now)}")
