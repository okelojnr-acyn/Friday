"""HR plan 8.2: announcements to everyone, a location or a team, with
who has seen them."""

import pytest
from friday_common.testing import make_principal


def who(principal, uid, email, role="member", team=(), locs=("*",)):
    p = make_principal(org_id=principal.org_id, role=role, email=email, team=team, locs=locs)
    return p.__class__(**{**p.__dict__, "user_id": uid})


@pytest.fixture
def events(monkeypatch):
    sent = []

    async def fake_publish(event_type, org_id, payload, **_):
        sent.append((event_type, payload))

    monkeypatch.setattr("app.announcements.publish_event", fake_publish)
    return sent


async def _staff(client, as_principal, principal):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    for name in ("Ann", "Ben", "Tom"):
        await client.post("/employees", json={"name": name, "email": f"{name.lower()}@x.test", "pay_rate_cents": 100})
    for uid, email in (("u-ann", "ann@x.test"), ("u-ben", "ben@x.test"), ("u-tom", "tom@x.test")):
        as_principal(who(principal, uid, email))
        await client.get("/me/wallet")  # claims the employee row
    return admin


async def test_to_everyone_and_who_has_seen_it(client, as_principal, principal, events):
    admin = await _staff(client, as_principal, principal)
    as_principal(admin)
    r = await client.post("/announcements", json={"title": "Stock count Saturday 7am", "body": "Everyone in by 7.", "audience": "everyone"})
    assert r.status_code == 201 and r.json()["recipients"] == 3
    [(kind, told)] = events
    assert kind == "minions.announcement.posted" and sorted(told["to_user_ids"]) == ["u-ann", "u-ben", "u-tom"]

    as_principal(who(principal, "u-ann", "ann@x.test"))
    [a] = (await client.get("/announcements")).json()
    assert a["title"] == "Stock count Saturday 7am" and a["read"] is False
    assert (await client.post(f"/announcements/{a['id']}/read")).status_code == 204
    assert (await client.get("/announcements")).json()[0]["read"] is True
    assert (await client.get(f"/announcements/{a['id']}/seen")).status_code == 403  # not hers to check

    as_principal(admin)
    [mine] = (await client.get("/announcements")).json()
    assert (mine["recipients"], mine["seen"]) == (3, 1)
    seen = {s["name"]: s["read_at"] for s in (await client.get(f"/announcements/{a['id']}/seen")).json()}
    assert seen["Ann"] and seen["Ben"] is None


async def test_who_may_send_to_whom(client, as_principal, principal, events):
    await _staff(client, as_principal, principal)
    # A team leader sends to his team only.
    tom = who(principal, "u-tom", "tom@x.test", role="team_leader", team=("u-ann",))
    as_principal(tom)
    assert (await client.post("/announcements", json={"title": "x", "audience": "everyone"})).status_code == 403
    r = await client.post("/announcements", json={"title": "Team huddle at 9", "audience": "team"})
    assert r.status_code == 201 and r.json()["recipients"] == 1
    # Staff send nothing; a manager only to their own locations.
    as_principal(who(principal, "u-ben", "ben@x.test"))
    assert (await client.post("/announcements", json={"title": "x", "audience": "team"})).status_code == 403
    bea = who(principal, "u-bea", "bea@x.test", role="branch_manager", locs=("11111111-1111-1111-1111-111111111111",))
    as_principal(bea)
    r = await client.post("/announcements", json={"title": "x", "audience": "location", "location_id": "22222222-2222-2222-2222-222222222222"})
    assert r.status_code == 403
