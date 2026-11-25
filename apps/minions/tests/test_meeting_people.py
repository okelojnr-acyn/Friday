"""HR plan 8.4.3: meetings between people of the business. You see the
ones you organise or are invited to (owners and admins all); invited
members are told and answer; only the organiser changes or cancels."""

import pytest
from friday_common.testing import make_principal

PEOPLE = {
    "u-bea": {"user_id": "u-bea", "role": "branch_manager", "name": "Bea", "email": "bea@x.test"},
    "u-sam": {"user_id": "u-sam", "role": "member", "name": "Sam", "email": "sam@x.test"},
    "u-ann": {"user_id": "u-ann", "role": "member", "name": "Ann", "email": "ann@x.test"},
}
SLOT = {"starts_at": "2026-11-27T07:00:00Z", "ends_at": "2026-11-27T08:00:00Z"}


def who(principal, uid, role="member"):
    p = make_principal(org_id=principal.org_id, role=role, email=PEOPLE[uid]["email"])
    return p.__class__(**{**p.__dict__, "user_id": uid})


@pytest.fixture
def events(monkeypatch):
    sent = []

    async def fake_publish(event_type, org_id, payload, deliver_at=None, **_):
        sent.append((event_type, {**payload, "_at": deliver_at}))

    async def person(_org, *, user_id="", email=""):
        return PEOPLE.get(user_id)

    monkeypatch.setattr("app.main.publish_event", fake_publish)
    monkeypatch.setattr("app.main.person_in_business", person)
    return sent


async def test_invited_members_are_told_see_it_and_answer(client, as_principal, principal, events):
    as_principal(who(principal, "u-bea", "branch_manager"))
    r = await client.post("/meetings", json={"title": "Stock count", **SLOT, "attendee_user_ids": ["u-sam"]})
    assert r.status_code == 201
    m = r.json()
    assert m["my_role"] == "organiser" and [a["user_id"] for a in m["attendees"]] == ["u-sam"]
    assert "sam@x.test" in m["attendee_emails"]  # Google Calendar invites them too
    [(kind, told)] = [e for e in events if e[0] != "minions.meeting.reminder"]
    assert kind == "minions.meeting.invited" and told["to_user_ids"] == ["u-sam"] and told["meeting"] == "Stock count"

    # Someone outside the business can't be invited.
    bad = await client.post("/meetings", json={"title": "x", **SLOT, "attendee_user_ids": ["u-nobody"]})
    assert bad.status_code == 422

    as_principal(who(principal, "u-sam"))
    [mine] = (await client.get("/meetings?mine=true")).json()
    assert mine["id"] == m["id"] and mine["my_role"] == "invited"
    r = await client.post(f"/meetings/{m['id']}/respond", json={"response": "accepted"})
    assert r.status_code == 200 and r.json()["my_role"] == "accepted"
    answered = [p for e, p in events if e == "minions.meeting.answered"]
    assert answered[0]["to_user_ids"] == ["u-bea"] and answered[0]["response"] == "accepted"
    # The invited can't change or cancel it.
    assert (await client.patch(f"/meetings/{m['id']}", json={"title": "Mine now"})).status_code == 403
    assert (await client.delete(f"/meetings/{m['id']}")).status_code == 403

    # Ann wasn't invited: she doesn't see it, can't answer it.
    as_principal(who(principal, "u-ann"))
    assert (await client.get("/meetings")).json() == []
    assert (await client.post(f"/meetings/{m['id']}/respond", json={"response": "accepted"})).status_code == 404

    # Owners see every meeting.
    as_principal(make_principal(org_id=principal.org_id, role="owner"))
    assert [x["id"] for x in (await client.get("/meetings")).json()] == [m["id"]]


async def test_moving_a_meeting_asks_again_and_cancelling_tells_everyone(client, as_principal, principal, events):
    as_principal(who(principal, "u-bea", "branch_manager"))
    m = (await client.post("/meetings", json={"title": "Stock count", **SLOT, "attendee_user_ids": ["u-sam"]})).json()
    as_principal(who(principal, "u-sam"))
    await client.post(f"/meetings/{m['id']}/respond", json={"response": "accepted"})

    as_principal(who(principal, "u-bea", "branch_manager"))
    r = await client.patch(f"/meetings/{m['id']}", json={"starts_at": "2026-11-27T09:00:00Z", "ends_at": "2026-11-27T10:00:00Z"})
    assert r.status_code == 200 and r.json()["attendees"][0]["response"] == "invited"
    moved = [p for e, p in events if e == "minions.meeting.changed"]
    assert moved and moved[0]["to_user_ids"] == ["u-sam"]

    r = await client.patch(f"/meetings/{m['id']}", json={"attendee_user_ids": ["u-sam", "u-ann"]})
    assert {a["user_id"] for a in r.json()["attendees"]} == {"u-sam", "u-ann"}
    assert [p["to_user_ids"] for e, p in events if e == "minions.meeting.invited"][-1] == ["u-ann"]

    assert (await client.delete(f"/meetings/{m['id']}")).status_code == 204
    cancelled = [p for e, p in events if e == "minions.meeting.cancelled"]
    assert sorted(cancelled[0]["to_user_ids"]) == ["u-ann", "u-sam"]


async def test_a_reminder_30_minutes_before_to_everyone_still_coming(client, as_principal, principal, events, kernel_auth_header):
    from datetime import UTC, datetime, timedelta

    starts = datetime.now(UTC) + timedelta(days=1)
    slot = {"starts_at": starts.isoformat(), "ends_at": (starts + timedelta(hours=1)).isoformat()}
    as_principal(who(principal, "u-bea", "branch_manager"))
    m = (await client.post("/meetings", json={"title": "Stock count", **slot, "attendee_user_ids": ["u-sam", "u-ann"]})).json()
    [reminder] = [p for e, p in events if e == "minions.meeting.reminder"]
    assert abs((reminder["_at"] - (starts - timedelta(minutes=30))).total_seconds()) < 1
    as_principal(who(principal, "u-ann"))
    await client.post(f"/meetings/{m['id']}/respond", json={"response": "declined"})

    def deliver(payload, eid):
        body = {"id": eid, "org_id": principal.org_id, "payload": {k: v for k, v in payload.items() if k != "_at"}}
        return client.post("/internal/webhooks/meeting-reminder", json=body, headers=kernel_auth_header)

    assert (await deliver(reminder, "r-1")).status_code == 204
    await deliver(reminder, "r-1")  # a repeat delivery: once
    [soon] = [p for e, p in events if e == "minions.meeting.soon"]
    assert sorted(soon["to_user_ids"]) == ["u-bea", "u-sam"]  # not Ann, who declined

    # Moved: the old reminder does nothing; a new one is scheduled.
    as_principal(who(principal, "u-bea", "branch_manager"))
    later = starts + timedelta(hours=2)
    await client.patch(f"/meetings/{m['id']}", json={"starts_at": later.isoformat(), "ends_at": (later + timedelta(hours=1)).isoformat()})
    await deliver(reminder, "r-2")
    assert len([e for e, _ in events if e == "minions.meeting.soon"]) == 1
    assert len([e for e, _ in events if e == "minions.meeting.reminder"]) == 2
