"""Plan section 12, step 2 in CRM: whose deals each role works."""

from dataclasses import replace


async def _deal(client, as_principal, who, name):
    as_principal(who)
    r = await client.post("/opportunities", json={"contact_name": name, "company": name, "value_cents": 1000})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_whose_deals_each_role_works(client, as_principal, principal):
    sam = replace(principal, user_id="11111111-1111-1111-1111-111111111111", role="member", perms=("sales",))
    ann = replace(principal, user_id="22222222-2222-2222-2222-222222222222", role="member", perms=("sales",))
    sams = await _deal(client, as_principal, sam, "Acme")
    anns = await _deal(client, as_principal, ann, "Beta")

    as_principal(sam)
    assert [o["id"] for o in (await client.get("/opportunities")).json()] == [sams]
    assert (await client.get(f"/opportunities/{anns}")).status_code == 404
    assert (await client.patch(f"/opportunities/{anns}", json={"stage": "won"})).status_code == 404

    lead = replace(principal, user_id="33333333-3333-3333-3333-333333333333", role="team_leader", team=(ann.user_id,))
    as_principal(lead)
    assert [o["id"] for o in (await client.get("/opportunities")).json()] == [anns]

    no_job = replace(principal, role="member", perms=("cashier",))
    as_principal(no_job)
    assert (await client.get("/opportunities")).status_code == 403

    as_principal(principal)  # admin
    assert {o["id"] for o in (await client.get("/opportunities")).json()} == {sams, anns}
