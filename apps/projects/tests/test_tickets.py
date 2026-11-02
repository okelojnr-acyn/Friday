async def test_create_ticket_defaults_to_open(client):
    resp = await client.post("/tickets", json={"subject": "Can't log in"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "open"


async def test_update_ticket_status(client):
    ticket = (await client.post("/tickets", json={"subject": "Can't log in"})).json()
    resp = await client.patch(f"/tickets/{ticket['id']}", json={"status": "resolved"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved"


async def test_update_ticket_rejects_invalid_status(client):
    ticket = (await client.post("/tickets", json={"subject": "Can't log in"})).json()
    resp = await client.patch(f"/tickets/{ticket['id']}", json={"status": "bogus"})
    assert resp.status_code == 422


async def test_ticket_due_at_roundtrips(client):
    created = (
        await client.post("/tickets", json={"subject": "Can't log in", "due_at": "2026-12-01T00:00:00Z"})
    ).json()
    assert created["due_at"].startswith("2026-12-01")

    cleared = (await client.patch(f"/tickets/{created['id']}", json={"due_at": None})).json()
    assert cleared["due_at"] is None


async def test_ticket_created_without_due_at_defaults_to_none(client):
    created = (await client.post("/tickets", json={"subject": "Can't log in"})).json()
    assert created["due_at"] is None
