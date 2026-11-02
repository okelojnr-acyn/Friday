from friday_common.testing import make_principal


async def test_create_project_defaults_to_active(client):
    resp = await client.post("/projects", json={"name": "Website Revamp"})
    assert resp.status_code == 201
    assert resp.json()["status"] == "active"


async def test_update_project_status(client):
    project = (await client.post("/projects", json={"name": "Website Revamp"})).json()
    resp = await client.patch(f"/projects/{project['id']}", json={"status": "archived"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "archived"


async def test_updating_someone_elses_project_is_not_found(client, as_principal, principal):
    project = (await client.post("/projects", json={"name": "Website Revamp"})).json()

    as_principal(make_principal())
    resp = await client.patch(f"/projects/{project['id']}", json={"status": "archived"})
    assert resp.status_code == 404

    as_principal(principal)
    assert (await client.get("/projects")).json()[0]["status"] == "active"
