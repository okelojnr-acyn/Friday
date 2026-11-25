"""HR plan phase 3: unpaid leave comes off the pay; requests go to whoever
covers for an approver, or past an approver who's away."""

from datetime import UTC, date, datetime, timedelta

import pytest
from friday_common.access import Approvers
from friday_common.testing import make_principal

PEOPLE = {
    "u-sam": {"user_id": "u-sam", "role": "member", "name": "Sam", "email": "sam@x.test"},
    "u-tom": {"user_id": "u-tom", "role": "team_leader", "name": "Tom", "email": "tom@x.test"},
    "u-bea": {"user_id": "u-bea", "role": "branch_manager", "name": "Bea", "email": "bea@x.test"},
}


def who(principal, uid, role="member"):
    p = make_principal(org_id=principal.org_id, role=role, email=PEOPLE[uid]["email"])
    return p.__class__(**{**p.__dict__, "user_id": uid})


@pytest.fixture
def setup(client, as_principal, principal, monkeypatch):
    sent = []

    async def fake_publish(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    async def person(_org, *, user_id="", email=""):
        return PEOPLE.get(user_id)

    async def line(_org, user_id):  # Sam -> Tom -> Bea
        chain = {"u-sam": ("u-tom", "u-bea"), "u-tom": ("u-bea",)}.get(user_id, ())
        return Approvers(limits={"team_leader": 200_000, "branch_manager": 2_000_000}, chain=tuple(PEOPLE[u] for u in chain), top=())

    monkeypatch.setattr("app.main.publish_event", fake_publish)
    monkeypatch.setattr("app.main.person_in_business", person)
    monkeypatch.setattr("app.main.approvers_for", line)

    async def go():
        admin = make_principal(org_id=principal.org_id, role="admin")
        as_principal(admin)
        ids = {}
        for uid, p in PEOPLE.items():
            ids[uid] = (await client.post("/employees", json={"name": p["name"], "email": p["email"], "pay_rate_cents": 2_000_000})).json()["id"]
        for uid in PEOPLE:
            as_principal(who(principal, uid))
            await client.put("/me/wallet", json={"wallet_address": "0xabc", "wallet_network": "base"})
        return admin, ids, sent

    return go


async def test_unpaid_days_come_off_the_pay(client, as_principal, principal, setup):
    admin, ids, _ = await setup()
    as_principal(who(principal, "u-sam"))
    t = (await client.post("/time_off", json={"kind": "unpaid", "starts_on": "2026-03-04", "ends_on": "2026-03-05"})).json()
    as_principal(admin)
    await client.patch(f"/time_off/{t['id']}/status", json={"status": "approved"})
    run = (
        await client.post(
            "/payroll_runs",
            json={"period_start": "2026-03-02T00:00:00Z", "period_end": "2026-03-27T00:00:00Z", "currency": "USD",
                  "employee_ids": [ids["u-sam"], ids["u-tom"]]},
        )
    ).json()
    by = {line["employee_name"]: line for line in run["lines"]}
    # 2 of the period's 20 working days: a tenth of 20,000 off.
    assert (by["Sam"]["unpaid_days"], by["Sam"]["unpaid_cents"], by["Sam"]["gross_amount_cents"]) == (2, 200_000, 1_800_000)
    assert by["Tom"]["unpaid_cents"] == 0 and by["Tom"]["gross_amount_cents"] == 2_000_000


async def test_requests_go_to_cover_or_past_someone_away(client, as_principal, principal, setup):
    admin, ids, sent = await setup()
    today = datetime.now(UTC).date()

    # Tom names Bea to cover for him this week: Sam's claim goes to Bea.
    as_principal(who(principal, "u-tom", "team_leader"))
    r = await client.put("/me/cover", json={"delegate_user_id": "u-bea", "starts_on": today.isoformat(), "ends_on": (today + timedelta(days=6)).isoformat()})
    assert r.status_code == 200 and r.json()["delegate_name"] == "Bea"
    assert [p["to_user_ids"] for e, p in sent if e == "minions.cover.set"] == [["u-bea"]]
    as_principal(who(principal, "u-sam"))
    claim = (await client.post("/expense_claims", json={"description": "taxi", "amount_cents": 1_000})).json()
    assert claim["waiting_on_name"] == "Bea"

    # No cover, but Tom is away today: it goes past him to Bea too.
    as_principal(who(principal, "u-tom", "team_leader"))
    assert (await client.delete("/me/cover")).status_code == 204
    off = (await client.post("/time_off", json={"kind": "annual", "starts_on": today.isoformat(), "ends_on": (today + timedelta(days=6)).isoformat()})).json()
    as_principal(admin)
    await client.patch(f"/time_off/{off['id']}/status", json={"status": "approved"})
    as_principal(who(principal, "u-sam"))
    claim = (await client.post("/expense_claims", json={"description": "lunch", "amount_cents": 1_000})).json()
    assert claim["waiting_on_name"] == "Bea"

    # Staff can't name cover; cover must be someone who approves.
    assert (await client.put("/me/cover", json={"delegate_user_id": "u-bea", "starts_on": "2026-12-01", "ends_on": "2026-12-02"})).status_code == 403
    as_principal(who(principal, "u-bea", "branch_manager"))
    r = await client.put("/me/cover", json={"delegate_user_id": "u-sam", "starts_on": "2026-12-01", "ends_on": "2026-12-02"})
    assert r.status_code == 422
    assert date.today() and ids
