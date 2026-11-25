"""HR plan phase 3: time off, decided up the line like a claim. Annual
leave counts against 21 working days a year; weekends aren't counted."""

import pytest
from friday_common.testing import make_principal


def _jane(principal):
    p = make_principal(org_id=principal.org_id, email="jane@example.com")
    return p.__class__(**{**p.__dict__, "user_id": "u-jane"})


@pytest.fixture
def events(monkeypatch):
    sent = []

    async def fake_publish(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    monkeypatch.setattr("app.main.publish_event", fake_publish)
    return sent


async def _setup(client, as_principal, principal):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    await client.post("/employees", json={"name": "Jane", "email": "jane@example.com", "pay_rate_cents": 5_000_000})
    as_principal(_jane(principal))
    await client.get("/me/wallet")  # claims the employee row
    return admin


async def test_ask_count_working_days_decide(client, as_principal, principal, events):
    admin = await _setup(client, as_principal, principal)
    # Tue 1 Dec to Mon 7 Dec 2026, a weekend in between: 5 working days.
    r = await client.post("/time_off", json={"kind": "annual", "starts_on": "2026-12-01", "ends_on": "2026-12-07", "note": "Home visit"})
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["days"] == 5 and t["status"] == "submitted"
    [asked] = [p for e, p in events if e == "minions.approval.needed"]
    assert asked["kind"] == "time_off" and asked["description"] == "Annual leave, 1-7 Dec, 5 days: Home visit"
    # Overlapping days are refused; a weekend alone has nothing to ask for.
    assert (await client.post("/time_off", json={"kind": "sick", "starts_on": "2026-12-03", "ends_on": "2026-12-03"})).status_code == 409
    assert (await client.post("/time_off", json={"kind": "unpaid", "starts_on": "2026-12-12", "ends_on": "2026-12-13"})).status_code == 422

    balance = (await client.get("/time_off/balance")).json()
    assert (balance["annual_taken"], balance["annual_left"]) == (5, 16)  # asked for counts too
    # More annual leave than is left is refused (ask for unpaid instead).
    r = await client.post("/time_off", json={"kind": "annual", "starts_on": "2026-01-05", "ends_on": "2026-02-13"})
    assert r.status_code == 422 and "unpaid" in r.json()["detail"]

    assert (await client.patch(f"/time_off/{t['id']}/status", json={"status": "approved"})).status_code == 403  # not her own
    as_principal(admin)
    assert (await client.patch(f"/time_off/{t['id']}/status", json={"status": "rejected"})).status_code == 422  # needs a reason
    r = await client.patch(f"/time_off/{t['id']}/status", json={"status": "approved"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    [decided] = [p for e, p in events if e == "minions.time_off.decided"]
    assert decided["to_user_ids"] == ["u-jane"]

    # On the calendar, with whose it is.
    cal = (await client.get("/time_off?start=2026-12-01&end=2026-12-31")).json()
    assert [(c["employee_name"], c["days"]) for c in cal] == [("Jane", 5)]


async def test_take_back_before_it_starts(client, as_principal, principal, events):
    await _setup(client, as_principal, principal)
    t = (await client.post("/time_off", json={"kind": "unpaid", "starts_on": "2027-03-01", "ends_on": "2027-03-02"})).json()
    r = await client.post(f"/time_off/{t['id']}/withdraw")
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    assert (await client.get("/time_off/balance")).json()["annual_taken"] == 0
