"""HR plan phase 2: salary advances. At most half of one pay, one open at
a time; decided like a claim; paid by M-Pesa/bank/cash/crypto; taken back
from the next pay runs, counted only once that pay is paid out."""

import pytest
from friday_common.testing import make_principal


def _staff(principal):
    p = make_principal(org_id=principal.org_id, email="jane@example.com")
    return p.__class__(**{**p.__dict__, "user_id": "u-jane"})


@pytest.fixture
def events(monkeypatch):
    sent = []

    async def fake_publish(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    monkeypatch.setattr("app.main.publish_event", fake_publish)
    return sent


async def _jane(client, as_principal, principal, pay=6_000_000):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    employee = (await client.post("/employees", json={"name": "Jane", "email": "jane@example.com", "pay_rate_cents": pay})).json()
    as_principal(_staff(principal))
    await client.put("/me/wallet", json={"wallet_address": "0xabc", "wallet_network": "base"})
    return admin, employee


async def test_ask_decide_pay(client, as_principal, principal, events):
    admin, _ = await _jane(client, as_principal, principal)  # KES 60,000 a month
    r = await client.post("/salary_advances", json={"amount_cents": 3_100_000, "months": 3})
    assert r.status_code == 422 and "half" in r.json()["detail"]  # more than 30,000
    r = await client.post("/salary_advances", json={"amount_cents": 3_000_000, "months": 3, "description": "school fees"})
    assert r.status_code == 201
    adv = r.json()
    assert adv["status"] == "submitted" and adv["waiting_on_name"] == "an owner or admin"
    asked = [p for e, p in events if e == "minions.approval.needed"]
    assert asked and asked[0]["kind"] == "salary_advance" and asked[0]["description"] == "school fees"
    again = await client.post("/salary_advances", json={"amount_cents": 100_000})
    assert again.status_code == 409  # one open at a time

    # Jane can't decide her own; an admin must give a reason to reject.
    assert (await client.patch(f"/salary_advances/{adv['id']}/status", json={"status": "approved"})).status_code == 403
    as_principal(admin)
    assert (await client.patch(f"/salary_advances/{adv['id']}/status", json={"status": "rejected"})).status_code == 422
    r = await client.patch(f"/salary_advances/{adv['id']}/status", json={"status": "approved"})
    assert r.status_code == 200 and r.json()["decided_by_name"]
    assert [p["to_user_ids"] for e, p in events if e == "minions.salary_advance.decided"] == [["u-jane"]]

    assert (await client.post(f"/salary_advances/{adv['id']}/pay", json={"method": "mpesa"})).status_code == 422
    r = await client.post(f"/salary_advances/{adv['id']}/pay", json={"method": "mpesa", "reference": "SKA1B2C3D4"})
    assert r.status_code == 200 and r.json()["status"] == "paid"
    [paid] = [p for e, p in events if e == "minions.salary_advance.paid"]
    assert paid["amount_cents"] == 3_000_000 and paid["method"] == "mpesa" and paid["to_user_ids"] == ["u-jane"]


async def test_payroll_takes_it_back_over_the_months(client, as_principal, principal, events, monkeypatch):
    admin, employee = await _jane(client, as_principal, principal)
    adv = (await client.post("/salary_advances", json={"amount_cents": 3_000_000, "months": 3})).json()
    as_principal(admin)
    await client.patch(f"/salary_advances/{adv['id']}/status", json={"status": "approved"})
    await client.post(f"/salary_advances/{adv['id']}/pay", json={"method": "cash"})

    async def fake_config(org_id, provider):
        return {"api_key": "test-key"}

    class FakeProvider:
        def __init__(self, config):
            pass

        async def request_payout(self, **kwargs):
            return {"id": "payout-1", "status": "pending"}

        async def get_payout_status(self, external_id):
            return {"status": "completed"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.AcynWalletProvider", FakeProvider)

    async def run_and_pay(month):
        run = (
            await client.post(
                "/payroll_runs",
                json={"period_start": f"2026-{month:02d}-01T00:00:00Z", "period_end": f"2026-{month:02d}-28T00:00:00Z",
                      "currency": "KES", "employee_ids": [employee["id"]]},
            )
        ).json()
        await client.post(f"/payroll_runs/{run['id']}/approve")
        await client.post(f"/payroll_runs/{run['id']}/pay")
        await client.post(f"/payroll_runs/{run['id']}/refresh-status")
        return run["lines"][0]

    first = await run_and_pay(3)
    assert first["advance_cents"] == 1_000_000  # a third of 30,000
    paid = [p for e, p in events if e == "minions.payroll_run.paid"][-1]
    assert paid["advance_cents"] == 1_000_000
    for month in (4, 5):
        await run_and_pay(month)
    as_principal(_staff(principal))
    [mine] = (await client.get("/salary_advances?mine=true")).json()
    assert mine["status"] == "recovered" and mine["recovered_cents"] == 3_000_000
    # Nothing more is taken once it's paid back.
    as_principal(admin)
    assert (await run_and_pay(6))["advance_cents"] == 0
