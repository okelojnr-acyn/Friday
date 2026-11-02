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
