"""HR plan 8.2: team sales this month against each person's target."""

from friday_common.testing import make_principal


def _sale(org_id, number, user_id, email, cents):
    return {"org_id": org_id, "payload": {"invoice_number": number, "amount_cents": cents,
                                          "cashier_user_id": user_id, "cashier_email": email, "lines": []}}


async def test_sales_against_target(client, as_principal, kernel_auth_header, principal):
    admin = make_principal(org_id=principal.org_id, role="admin")
    as_principal(admin)
    ann = (await client.post("/employees", json={"name": "Ann", "email": principal.email})).json()
    await client.post("/employees", json={"name": "Ben", "email": "ben@x.test"})
    as_principal(principal)  # Ann claims her row
    await client.get("/me/wallet")
    for n, cents in (("POS-1", 30_000), ("POS-2", 20_000)):
        r = await client.post("/internal/webhooks/pos-sale", headers=kernel_auth_header,
                              json=_sale(principal.org_id, n, principal.user_id, principal.email, cents))
        assert r.status_code == 204

    # Ann can't set her own target; the admin can.
    assert (await client.put(f"/team/targets/{ann['id']}", json={"sales_target_cents": 1})).status_code == 403
    as_principal(admin)
    assert (await client.put(f"/team/targets/{ann['id']}", json={"sales_target_cents": 100_000})).status_code == 200

    out = (await client.get("/team/sales")).json()
    by = {p["name"]: p for p in out["people"]}
    assert (by["Ann"]["sold_cents"], by["Ann"]["sales"], by["Ann"]["target_cents"]) == (50_000, 2, 100_000)
    assert by["Ben"]["sold_cents"] == 0 and out["people"][0]["name"] == "Ann"
    assert (out["sold_cents"], out["target_cents"]) == (50_000, 100_000)
    # Another month has none of it.
    assert (await client.get("/team/sales?month=2020-01")).json()["sold_cents"] == 0

    # Ann sees only herself.
    as_principal(principal)
    mine = (await client.get("/team/sales")).json()["people"]
    assert [p["name"] for p in mine] == ["Ann"] and mine[0]["me"] is True
