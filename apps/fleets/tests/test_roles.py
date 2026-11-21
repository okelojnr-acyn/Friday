"""Plan section 12, step 2 in Fleets: logistics staff log fuel and
maintenance; only managers change the fleet."""

from dataclasses import replace


async def test_logistics_staff_log_but_do_not_change_the_fleet(client, as_principal, principal):
    as_principal(principal)  # admin
    v = await client.post("/vehicles", json={"name": "Lorry 1", "plate_number": "KDA 001A"})
    assert v.status_code == 201, v.text

    driver = replace(principal, role="member", perms=("logistics",))
    as_principal(driver)
    assert (await client.get("/vehicles")).status_code == 200
    assert (await client.post("/vehicles", json={"name": "Lorry 2"})).status_code == 403
    assert (await client.post("/drivers", json={"name": "Otieno"})).status_code == 403

    cashier = replace(principal, role="member", perms=("cashier",))
    as_principal(cashier)
    assert (await client.get("/vehicles")).status_code == 403

    boss = replace(principal, role="branch_manager", locs=("*",))
    as_principal(boss)
    assert (await client.post("/drivers", json={"name": "Otieno"})).status_code == 201
