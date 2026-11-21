"""Paystack inside Friday (plan 15.3): POS checkout, invoice pay links,
the signed webhook and the till's status poll. Never calls Paystack: the
provider is replaced by a fake that answers initialize and verify."""

import hashlib
import hmac
import json
from dataclasses import replace

import pytest

from app.paystack_pay import method_for, parse_reference

SECRET = "sk_test_abc"


async def _config(org_id, provider):
    return {"secret_key": SECRET} if provider == "paystack" else {}


@pytest.fixture
def paystack(monkeypatch):
    """A fake Paystack: `verified` is what verify answers per reference."""
    state = {"verified": {}, "started": []}

    class FakePaystack:
        def __init__(self, config):
            assert config["secret_key"] == SECRET

        async def create_payment_intent(self, amount_cents, currency, metadata):
            state["started"].append((amount_cents, currency, metadata))
            return {"id": metadata["reference"], "redirect_url": f"https://checkout.paystack.com/{metadata['reference']}"}

        async def verify(self, reference):
            return state["verified"].get(reference, {"status": "abandoned", "amount": 0, "currency": "", "channel": ""})

    monkeypatch.setattr("app.paystack_pay.get_integration_config", _config)
    monkeypatch.setattr("app.paystack_pay.PaystackProvider", FakePaystack)
    monkeypatch.setattr("app.webhooks.get_integration_config", _config)
    return state


def _sale(cents=1000):
    return {
        "lines": [{"description": "Rice", "quantity": 1, "unit_price_cents": cents}],
        "amount_cents": cents,
        "currency": "KES",
    }


def _signed(body: dict) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    sig = hmac.new(SECRET.encode(), raw, hashlib.sha512).hexdigest()
    return raw, {"x-paystack-signature": sig, "content-type": "application/json"}


async def _start_sale(client, paystack, cents=1000) -> tuple[str, str]:
    r = await client.post("/pos/sales/pay-with-paystack", json=_sale(cents))
    assert r.status_code == 201, r.text
    reference = paystack["started"][-1][2]["reference"]
    return r.json()["invoice_id"], reference


def test_reference_and_channel_mapping():
    org = "11111111-1111-1111-1111-111111111111"
    inv = "22222222-2222-2222-2222-222222222222"
    assert parse_reference(f"{org}.{inv}.0a1b2c3d") == (org, inv)
    assert parse_reference("T123456789") is None
    assert parse_reference(f"{org}.{inv}.0a1b2c3d.extra") is None
    assert method_for("mobile_money") == "mpesa"
    assert method_for("card") == "card"
    assert method_for("bank_transfer") == "bank_transfer"


async def test_pos_paystack_needs_a_connected_account(client):
    r = await client.post("/pos/sales/pay-with-paystack", json=_sale())
    assert r.status_code == 400


async def test_pos_sale_waits_until_paystack_says_paid(client, principal, paystack):
    invoice_id, reference = await _start_sale(client, paystack)
    amount, currency, _ = paystack["started"][-1]
    assert (amount, currency) == (1000, "KES")
    assert parse_reference(reference) == (principal.org_id, invoice_id)

    # Not paid yet: the poll asks Paystack and the sale stays pending.
    assert (await client.get(f"/pos/sales/{invoice_id}/status")).json()["status"] == "pending"

    paystack["verified"][reference] = {"status": "success", "amount": 1000, "currency": "KES", "channel": "mobile_money"}
    assert (await client.get(f"/pos/sales/{invoice_id}/status")).json()["status"] == "paid"
    inv = (await client.get(f"/invoices/{invoice_id}")).json()
    assert [(p["method"], p["amount_cents"]) for p in inv["payments"]] == [("mpesa", 1000)]


@pytest.mark.parametrize(
    "answer",
    [
        {"status": "success", "amount": 999, "currency": "KES", "channel": "card"},  # short
        {"status": "success", "amount": 1000, "currency": "USD", "channel": "card"},  # wrong currency
        {"status": "failed", "amount": 1000, "currency": "KES", "channel": "card"},
    ],
)
async def test_a_wrong_or_failed_payment_leaves_the_sale_unpaid(client, paystack, answer):
    invoice_id, reference = await _start_sale(client, paystack)
    paystack["verified"][reference] = answer
    assert (await client.get(f"/pos/sales/{invoice_id}/status")).json()["status"] == "pending"


async def test_webhook_checks_the_signature_then_settles_once(client, paystack):
    invoice_id, reference = await _start_sale(client, paystack)
    paystack["verified"][reference] = {"status": "success", "amount": 1000, "currency": "KES", "channel": "card"}
    body = {"event": "charge.success", "data": {"reference": reference, "amount": 1000}}

    raw, headers = _signed(body)
    bad = dict(headers, **{"x-paystack-signature": "0" * 128})
    assert (await client.post("/external/webhooks/paystack", content=raw, headers=bad)).status_code == 400
    missing = {"content-type": "application/json"}
    assert (await client.post("/external/webhooks/paystack", content=raw, headers=missing)).status_code == 400
    assert (await client.get(f"/pos/sales/{invoice_id}/status")).json()["status"] == "paid"  # poll settles anyway

    # A replayed webhook (and further polls) record nothing more.
    for _ in range(2):
        assert (await client.post("/external/webhooks/paystack", content=raw, headers=headers)).status_code == 200
    inv = (await client.get(f"/invoices/{invoice_id}")).json()
    assert [(p["method"], p["amount_cents"]) for p in inv["payments"]] == [("card", 1000)]


async def test_webhook_alone_settles_a_sale(client, paystack):
    invoice_id, reference = await _start_sale(client, paystack)
    paystack["verified"][reference] = {"status": "success", "amount": 1000, "currency": "KES", "channel": "card"}
    raw, headers = _signed({"event": "charge.success", "data": {"reference": reference}})
    assert (await client.post("/external/webhooks/paystack", content=raw, headers=headers)).status_code == 200
    inv = (await client.get(f"/invoices/{invoice_id}")).json()
    assert inv["status"] == "paid"


async def test_webhook_ignores_references_that_are_not_ours(client, paystack):
    raw, headers = _signed({"event": "charge.success", "data": {"reference": "T123"}})
    r = await client.post("/external/webhooks/paystack", content=raw, headers=headers)
    assert r.status_code == 200 and "ignored" in r.json()


async def test_invoice_pay_link_takes_the_balance(client, paystack):
    inv = (
        await client.post(
            "/invoices",
            json={"currency": "KES", "lines": [{"description": "Consulting", "quantity": 1, "unit_price_cents": 5000}]},
        )
    ).json()
    await client.post(f"/invoices/{inv['id']}/payments", json={"amount_cents": 2000, "method": "cash"})

    r = await client.post(f"/invoices/{inv['id']}/paystack-link")
    assert r.status_code == 201, r.text
    assert r.json()["redirect_url"].startswith("https://checkout.paystack.com/")
    amount, _, meta = paystack["started"][-1]
    assert amount == 3000

    paystack["verified"][meta["reference"]] = {"status": "success", "amount": 3000, "currency": "KES", "channel": "card"}
    raw, headers = _signed({"event": "charge.success", "data": {"reference": meta["reference"]}})
    assert (await client.post("/external/webhooks/paystack", content=raw, headers=headers)).status_code == 200
    out = (await client.get(f"/invoices/{inv['id']}")).json()
    assert out["status"] == "paid"
    assert sorted(p["method"] for p in out["payments"]) == ["card", "cash"]


async def test_a_paid_invoice_gets_no_link(client, paystack):
    inv = (await client.post("/invoices", json={})).json()
    assert (await client.post(f"/invoices/{inv['id']}/paystack-link")).status_code == 400


async def test_a_till_chooses_its_payment_methods(client, as_principal, principal, a_till):
    as_principal(replace(principal, role="admin"))
    r = await client.patch(f"/pos/registers/{a_till}", json={"payment_methods": ["cash", "paystack"]})
    assert r.status_code == 200 and r.json()["payment_methods"] == ["cash", "paystack"]
    assert (await client.patch(f"/pos/registers/{a_till}", json={"payment_methods": ["bitcoin"]})).status_code == 422
    # Renaming leaves the methods alone; null goes back to the business's list.
    r = await client.patch(f"/pos/registers/{a_till}", json={"name": "Front"})
    assert r.json()["payment_methods"] == ["cash", "paystack"]
    r = await client.patch(f"/pos/registers/{a_till}", json={"payment_methods": None})
    assert r.json()["payment_methods"] is None
