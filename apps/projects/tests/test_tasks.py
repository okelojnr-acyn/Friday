from friday_common.testing import make_principal


async def test_create_task_applies_defaults(client):
    resp = await client.post("/tasks", json={"title": "Draft homepage copy"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "todo"
    assert body["priority"] == "medium"
    assert body["project_id"] is None


async def test_task_links_to_a_project(client):
    project = (await client.post("/projects", json={"name": "Website Revamp"})).json()
    task = (
        await client.post("/tasks", json={"title": "Draft homepage copy", "project_id": project["id"]})
    ).json()
    assert task["project_id"] == project["id"]


async def test_list_tasks_filters_by_project(client):
    project_a = (await client.post("/projects", json={"name": "A"})).json()
    project_b = (await client.post("/projects", json={"name": "B"})).json()
    await client.post("/tasks", json={"title": "A task", "project_id": project_a["id"]})
    await client.post("/tasks", json={"title": "B task", "project_id": project_b["id"]})
    await client.post("/tasks", json={"title": "Unassigned task"})

    resp = await client.get("/tasks", params={"project_id": project_a["id"]})
    titles = [t["title"] for t in resp.json()]
    assert titles == ["A task"]


async def test_create_task_rejects_invalid_status_or_priority(client):
    assert (await client.post("/tasks", json={"title": "x", "status": "bogus"})).status_code == 422
    assert (await client.post("/tasks", json={"title": "x", "priority": "bogus"})).status_code == 422


async def test_update_task_status(client):
    task = (await client.post("/tasks", json={"title": "x"})).json()
    resp = await client.patch(f"/tasks/{task['id']}", json={"status": "done"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


async def test_org_isolation_on_tasks(client, as_principal, principal):
    task = (await client.post("/tasks", json={"title": "x"})).json()

    as_principal(make_principal())
    assert (await client.get("/tasks")).json() == []
    assert (await client.patch(f"/tasks/{task['id']}", json={"status": "done"})).status_code == 404

    as_principal(principal)
    assert (await client.get("/tasks")).json()[0]["status"] == "todo"
