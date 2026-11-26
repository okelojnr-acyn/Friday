"""Spending plan part C: paying out of the till is off by default; when
the owner allows it, a payout (at most the policy's most for one slip) is
on the shift, comes off the cash expected and is booked."""

import pytest
from friday_common.access import STANDARD_SPENDING

pytestmark = pytest.mark.usefixtures("a_till")


@pytest.fixture
def policy(monkeypatch):
    now = dict(STANDARD_SPENDING)  # Standard: off, at most 2,000 a slip
    sent = []

    async def read(_org):
        return now

    async def fake_publish(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    monkeypatch.setattr("app.registers.spending_policy", read)
    monkeypatch.setattr("app.registers.publish_event", fake_publish)
    return now, sent


async def test_paying_out_of_the_till(client, policy):
    now, sent = policy
    shift = (await client.post("/pos/shifts/open", json={"opening_float_cents": 10_000})).json()
    pay = lambda cents: client.post(f"/pos/shifts/{shift['id']}/paid_outs", json={"amount_cents": cents, "description": "Water delivery"})  # noqa: E731
    r = await pay(1_500)
    assert r.status_code == 403 and "petty cash" in r.json()["detail"]

    now["till_payouts"] = True
    assert (await pay(250_000)).status_code == 422  # over 2,000
    r = await pay(1_500)
    assert r.status_code == 201
    assert [p["amount_cents"] for e, p in sent if e == "invoicing.till.paid_out"] == [1_500]
    assert [p["amount_cents"] for p in (await client.get(f"/pos/shifts/{shift['id']}/paid_outs")).json()] == [1_500]

    closed = (await client.post(f"/pos/shifts/{shift['id']}/close", json={"closing_count_cents": 8_500})).json()
    assert closed["expected_cents"] == 8_500 and closed["summary"]["paid_out_cents"] == 1_500
    assert (await pay(100)).status_code == 400  # closed
