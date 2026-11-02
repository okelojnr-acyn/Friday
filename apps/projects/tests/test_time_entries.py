import uuid

from friday_common.testing import make_principal


async def test_create_time_entry_requires_existing_task(client):
    resp = await client.post("/time_entries", json={"task_id": str(uuid.uuid4()), "minutes": 30})
    assert resp.status_code == 404


async def test_time_entry_create_and_list_roundtrip(client):
    task = (await client.post("/tasks", json={"title": "Write proposal"})).json()

    created = (
        await client.post("/time_entries", json={"task_id": task["id"], "minutes": 45, "note": "first draft"})
    ).json()
    assert created["task_id"] == task["id"]
    assert created["minutes"] == 45

    listed = (await client.get("/time_entries")).json()
    assert len(listed) == 1

    filtered = (await client.get("/time_entries", params={"task_id": task["id"]})).json()
    assert len(filtered) == 1


async def test_time_entries_are_org_isolated(client, as_principal, principal):
    task = (await client.post("/tasks", json={"title": "Write proposal"})).json()
    await client.post("/time_entries", json={"task_id": task["id"], "minutes": 15})

    as_principal(make_principal())  # a different org entirely
    assert (await client.get("/time_entries")).json() == []

    as_principal(principal)
    assert len((await client.get("/time_entries")).json()) == 1
