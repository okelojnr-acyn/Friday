from friday_common.testing import make_principal


def _as_admin(as_principal, principal):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    return admin


async def test_member_cannot_create_employee(client):
    resp = await client.post("/employees", json={"name": "Jane", "email": "jane@example.com"})
    assert resp.status_code == 403


async def test_admin_can_create_employee(client, as_principal, principal):
    _as_admin(as_principal, principal)
    resp = await client.post("/employees", json={"name": "Jane", "email": "jane@example.com", "department": "Sales"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Jane"
    assert body["user_id"] == ""  # unclaimed until she self-serves


async def test_cannot_create_duplicate_employee_email(client, as_principal, principal):
    _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": "jane@example.com"})
    resp = await client.post("/employees", json={"name": "Jane Again", "email": "jane@example.com"})
    assert resp.status_code == 409


async def test_create_employee_rejects_unknown_pay_frequency(client, as_principal, principal):
    _as_admin(as_principal, principal)
    resp = await client.post(
        "/employees", json={"name": "Jane", "email": "jane@example.com", "pay_frequency": "bogus"}
    )
    assert resp.status_code == 422


async def test_any_member_can_list_employees(client, as_principal, principal):
    _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": "jane@example.com"})

    as_principal(principal)  # back to a plain member
    resp = await client.get("/employees")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_member_cannot_update_employee(client, as_principal, principal):
    admin = _as_admin(as_principal, principal)
    created = (await client.post("/employees", json={"name": "Jane", "email": "jane@example.com"})).json()

    as_principal(principal)
    resp = await client.patch(
        f"/employees/{created['id']}", json={"name": "Jane Doe", "email": "jane@example.com"}
    )
    assert resp.status_code == 403
    as_principal(admin)  # restore for teardown consistency


async def test_admin_can_update_employee(client, as_principal, principal):
    _as_admin(as_principal, principal)
    created = (await client.post("/employees", json={"name": "Jane", "email": "jane@example.com"})).json()

    resp = await client.patch(
        f"/employees/{created['id']}",
        json={"name": "Jane Doe", "email": "jane@example.com", "department": "Engineering"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Jane Doe"
    assert resp.json()["department"] == "Engineering"


async def test_org_isolation_on_employees(client, as_principal, principal):
    _as_admin(as_principal, principal)
    await client.post("/employees", json={"name": "Jane", "email": "jane@example.com"})

    as_principal(make_principal())  # different org entirely
    resp = await client.get("/employees")
    assert resp.json() == []
