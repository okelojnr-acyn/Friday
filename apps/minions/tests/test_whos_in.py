"""HR plan phase 3: who's in today, for the people a leader looks after."""

from datetime import UTC, datetime, timedelta

from friday_common.testing import make_principal


async def test_in_away_and_not_yet(client, as_principal, principal, monkeypatch):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    for name in ("Ann", "Ben", "Cy"):
        await client.post("/employees", json={"name": name, "email": f"{name.lower()}@x.test", "pay_rate_cents": 100})
    for uid, email in (("u-ann", "ann@x.test"), ("u-ben", "ben@x.test"), ("u-cy", "cy@x.test")):
        p = make_principal(org_id=principal.org_id, email=email)
        as_principal(p.__class__(**{**p.__dict__, "user_id": uid}))
        await client.get("/me/wallet")  # claims the employee row
    # Cy is on approved sick leave today.
    today = datetime.now(UTC).date()
    t = (await client.post("/time_off", json={"kind": "sick", "starts_on": today.isoformat(), "ends_on": (today + timedelta(days=6)).isoformat()})).json()
    as_principal(admin)
    await client.patch(f"/time_off/{t['id']}/status", json={"status": "approved"})

    async def seen(org_id, since, user_ids):
        assert set(user_ids) == {"u-ann", "u-ben", "u-cy"}
        return {"u-ann": {"user_id": "u-ann", "till_at": "2026-11-26T05:02:00Z", "till": "Till 2", "last_at": "2026-11-26T09:40:00Z"}}

    monkeypatch.setattr("app.presence._seen", seen)
    rows = (await client.get("/team/today")).json()
    assert [(r["name"], r["state"]) for r in rows] == [("Ann", "in"), ("Ben", "not_yet"), ("Cy", "away")]
    assert rows[0]["till"] == "Till 2" and rows[2]["leave"] == "sick"

    # Staff don't see the team.
    as_principal(make_principal(org_id=principal.org_id, role="member"))
    assert (await client.get("/team/today")).status_code == 403
