"""Meeting scheduling, synced to Google Calendar via
friday_common.integrations.GoogleCalendarProvider -- same
monkeypatch-the-module-level-import pattern
test_wallet_and_expense_claims.py already uses for AcynWalletProvider,
since get_integration_config makes a real HTTP call to the kernel that
isn't running in this test environment.
"""


async def test_create_meeting_stays_pending_when_calendar_not_connected(client, principal):
    resp = await client.post(
        "/meetings",
        json={
            "title": "Standup",
            "starts_at": "2026-11-10T09:00:00Z",
            "ends_at": "2026-11-10T09:15:00Z",
            "attendee_emails": "a@example.com, b@example.com",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["sync_status"] == "pending"
    assert body["calendar_event_id"] == ""
    assert "not connected" in body["sync_error"]
    assert body["created_by_email"] == principal.email


async def test_create_meeting_rejects_end_before_start(client):
    resp = await client.post(
        "/meetings",
        json={"title": "Bad", "starts_at": "2026-11-10T09:00:00Z", "ends_at": "2026-11-10T08:00:00Z"},
    )
    assert resp.status_code == 422


async def test_create_meeting_syncs_to_calendar_when_connected(client, monkeypatch):
    async def fake_config(org_id, provider):
        return {"client_id": "x", "client_secret": "y", "refresh_token": "z"}

    captured = {}

    class FakeProvider:
        def __init__(self, config):
            pass

        async def create_event(self, title, start_iso, end_iso, attendees):
            captured.update(title=title, start_iso=start_iso, end_iso=end_iso, attendees=attendees)
            return {"id": "evt-1", "htmlLink": "https://calendar.google.com/evt-1"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.GoogleCalendarProvider", FakeProvider)

    resp = await client.post(
        "/meetings",
        json={
            "title": "Planning",
            "starts_at": "2026-11-10T10:00:00Z",
            "ends_at": "2026-11-10T11:00:00Z",
            "attendee_emails": "a@example.com, b@example.com",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["sync_status"] == "synced"
    assert body["calendar_event_id"] == "evt-1"
    assert body["calendar_link"] == "https://calendar.google.com/evt-1"
    assert captured["attendees"] == ["a@example.com", "b@example.com"]


async def test_update_meeting_resyncs_existing_calendar_event(client, monkeypatch):
    async def fake_config(org_id, provider):
        return {"client_id": "x", "client_secret": "y", "refresh_token": "z"}

    captured = {}

    class FakeProvider:
        def __init__(self, config):
            pass

        async def create_event(self, title, start_iso, end_iso, attendees):
            return {"id": "evt-2", "htmlLink": "https://calendar.google.com/evt-2"}

        async def update_event(self, event_id, title, start_iso, end_iso, attendees):
            captured.update(event_id=event_id, title=title)
            return {"id": event_id, "htmlLink": "https://calendar.google.com/evt-2"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.GoogleCalendarProvider", FakeProvider)

    created = (
        await client.post(
            "/meetings",
            json={"title": "1:1", "starts_at": "2026-11-10T10:00:00Z", "ends_at": "2026-11-10T10:30:00Z"},
        )
    ).json()

    resp = await client.patch(f"/meetings/{created['id']}", json={"title": "1:1 (moved)"})
    assert resp.status_code == 200
    assert resp.json()["sync_status"] == "synced"
    assert captured["event_id"] == "evt-2"
    assert captured["title"] == "1:1 (moved)"


async def test_update_meeting_skips_resync_when_nothing_calendar_cares_about_changed(client, monkeypatch):
    calls = {"count": 0}

    async def fake_config(org_id, provider):
        calls["count"] += 1
        return {"client_id": "x", "client_secret": "y", "refresh_token": "z"}

    class FakeProvider:
        def __init__(self, config):
            pass

        async def create_event(self, title, start_iso, end_iso, attendees):
            return {"id": "evt-3", "htmlLink": "https://calendar.google.com/evt-3"}

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.GoogleCalendarProvider", FakeProvider)

    created = (
        await client.post(
            "/meetings",
            json={"title": "Review", "starts_at": "2026-11-10T10:00:00Z", "ends_at": "2026-11-10T10:30:00Z"},
        )
    ).json()
    assert calls["count"] == 1

    # created_by_email isn't one of the calendar-relevant fields -- this
    # should patch the row without calling the calendar config lookup
    # again.
    resp = await client.patch(f"/meetings/{created['id']}", json={"created_by_email": "someone-else@example.com"})
    assert resp.status_code == 200
    assert calls["count"] == 1


async def test_delete_meeting_cancels_the_calendar_event(client, monkeypatch):
    async def fake_config(org_id, provider):
        return {"client_id": "x", "client_secret": "y", "refresh_token": "z"}

    deleted = {}

    class FakeProvider:
        def __init__(self, config):
            pass

        async def create_event(self, title, start_iso, end_iso, attendees):
            return {"id": "evt-4", "htmlLink": "https://calendar.google.com/evt-4"}

        async def delete_event(self, event_id):
            deleted["event_id"] = event_id

    monkeypatch.setattr("app.main.get_integration_config", fake_config)
    monkeypatch.setattr("app.main.GoogleCalendarProvider", FakeProvider)

    created = (
        await client.post(
            "/meetings",
            json={"title": "Cancel me", "starts_at": "2026-11-10T10:00:00Z", "ends_at": "2026-11-10T10:30:00Z"},
        )
    ).json()

    resp = await client.delete(f"/meetings/{created['id']}")
    assert resp.status_code == 204
    assert deleted["event_id"] == "evt-4"
    assert (await client.get("/meetings")).json() == []


async def test_meetings_are_org_isolated(client, as_principal, principal):
    await client.post(
        "/meetings",
        json={"title": "Org A meeting", "starts_at": "2026-11-10T10:00:00Z", "ends_at": "2026-11-10T10:30:00Z"},
    )

    from friday_common.testing import make_principal

    other_org = make_principal(role="member")
    as_principal(other_org)
    assert (await client.get("/meetings")).json() == []
