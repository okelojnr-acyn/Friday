"""Plan section 12, step 2 in Invoicing: who may sell at which till, whose
sales each role sees, and who handles invoices and customers."""

import uuid
from dataclasses import replace

WEST = str(uuid.uuid4())
EAST = str(uuid.uuid4())


def sale(cents=1000, **kw):
    body = {
        "client_sale_id": str(uuid.uuid4()),
        "currency": "KES",
        "method": "cash",
        "amount_cents": cents,
        "lines": [{"description": "Soda", "quantity": 1, "unit_price_cents": cents}],
    }
    body.update(kw)
    return body


async def _till(client, as_principal, admin, name, location):
    as_principal(admin)
    r = await client.post("/pos/registers", json={"name": name, "location_id": location})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _open(client, as_principal, who, till):
    as_principal(who)
    r = await client.post("/pos/shifts/open", json={"register_id": till, "opening_float_cents": 0})
    return r


async def test_only_cashiers_sell_and_only_at_their_locations(client, as_principal, principal):
    admin = principal
    west = await _till(client, as_principal, admin, "West 1", WEST)
    east = await _till(client, as_principal, admin, "East 1", EAST)

    stocker = replace(principal, user_id="u-stock", role="member", perms=("warehouse",), locs=(WEST,))
    r = await _open(client, as_principal, stocker, west)
    assert r.status_code == 403 and "ask" in r.json()["detail"]

    sam = replace(principal, user_id="u-sam", role="member", perms=("cashier",), locs=(WEST,))
    assert (await _open(client, as_principal, sam, east)).status_code == 403  # not his location
    shift = await _open(client, as_principal, sam, west)
    assert shift.status_code == 201, shift.text
    made = await client.post("/pos/sales", json=sale(shift_id=shift.json()["id"]))
    assert made.status_code == 201, made.text
    # A sale at West is filed at West.
    as_principal(admin)
    inv = (await client.get(f"/invoices/{made.json()['id']}")).json()
    assert inv["id"] == made.json()["id"]


async def test_whose_sales_each_role_sees(client, as_principal, principal):
    admin = principal
    west = await _till(client, as_principal, admin, "West 2", WEST)
    sam = replace(principal, user_id="u-sam2", role="member", perms=("cashier",), locs=(WEST,))
    ann = replace(principal, user_id="u-ann2", role="member", perms=("cashier",), locs=(WEST,))
    shift = (await _open(client, as_principal, sam, west)).json()
    await client.post("/pos/sales", json=sale(100, shift_id=shift["id"]))
    as_principal(ann)
    await client.post("/pos/sales", json=sale(200, shift_id=shift["id"]))

    from datetime import UTC, datetime

    today = datetime.now(UTC).date().isoformat()

    async def seen(who):
        as_principal(who)
        r = await client.get("/pos/sales", params={"day": today})
        assert r.status_code == 200, r.text
        return sorted(s["total_cents"] for s in r.json())

    assert await seen(sam) == [100]  # own
    lead = replace(principal, user_id="u-lead2", role="team_leader", perms=(), locs=(WEST,), team=("u-ann2",))
    assert await seen(lead) == [200]  # their team (and themselves)
    boss = replace(principal, user_id="u-boss2", role="branch_manager", locs=(WEST,))
    assert 100 in await seen(boss) and 200 in await seen(boss)
    elsewhere = replace(principal, user_id="u-boss3", role="branch_manager", locs=(EAST,))
    assert 100 not in await seen(elsewhere)


async def test_invoices_and_customers_by_role(client, as_principal, principal):
    staff = replace(principal, role="member", perms=("cashier",))
    as_principal(staff)
    assert (await client.post("/invoices", json={})).status_code == 403
    assert (await client.get("/invoices")).status_code == 403
    assert (await client.get("/customers")).status_code == 200  # a cashier serves customers
    no_job = replace(principal, role="member", perms=("warehouse",))
    as_principal(no_job)
    assert (await client.get("/customers")).status_code == 403
    viewer = replace(principal, role="viewer")
    as_principal(viewer)
    assert (await client.get("/invoices")).status_code == 200
    boss = replace(principal, role="branch_manager", locs=(WEST,))
    as_principal(boss)
    assert (await client.get("/reports/ar-aging")).status_code == 403  # whole-business report


async def test_a_branch_manager_runs_tills_at_their_locations_only(client, as_principal, principal):
    boss = replace(principal, role="branch_manager", locs=(WEST,))
    as_principal(boss)
    assert (await client.post("/pos/registers", json={"name": "No place"})).status_code == 422
    assert (await client.post("/pos/registers", json={"name": "East 9", "location_id": EAST})).status_code == 403
    r = await client.post("/pos/registers", json={"name": "West 9", "location_id": WEST})
    assert r.status_code == 201, r.text
    moved = await client.patch(f"/pos/registers/{r.json()['id']}", json={"location_id": EAST})
    assert moved.status_code == 403


def _approval(principal, sub, role, team=(), locs=("*",), via="pos-approval", minutes=2):
    """What the kernel's POST /auth/pos/approve signs."""
    from datetime import UTC, datetime, timedelta

    import jwt
    from friday_common.settings import get_settings

    s = get_settings()
    claims = {
        "sub": sub, "org_id": principal.org_id, "role": role, "email": f"{sub}@x.test", "via": via,
        "team": list(team), "locs": list(locs), "exp": datetime.now(UTC) + timedelta(minutes=minutes),
    }
    return jwt.encode(claims, s.jwt_secret, algorithm=s.jwt_algorithm)


async def test_staff_returns_need_a_team_leader_or_manager_at_the_till(client, as_principal, principal):
    admin = principal
    west = await _till(client, as_principal, admin, "West R", WEST)
    sam = replace(principal, user_id="u-sam-r", role="member", perms=("cashier",), locs=(WEST,))
    shift = (await _open(client, as_principal, sam, west)).json()
    small = (await client.post("/pos/sales", json=sale(1000, shift_id=shift["id"]))).json()
    big = (await client.post("/pos/sales", json=sale(300000, shift_id=shift["id"]))).json()

    def ret(s, token=None, shift_id=shift["id"]):
        q = f"?shift_id={shift_id}" if shift_id else ""
        return client.post(f"/pos/sales/{s['number']}/return{q}", headers={"X-Friday-Approval": token} if token else {})

    r = await ret(small)
    assert r.status_code == 428 and "approval" in r.json()["detail"]
    # Not over Sam: another team's leader; Sam approving himself; a sign-in, not an approval.
    assert (await ret(small, _approval(principal, "u-tl-x", "team_leader", team=("u-other",)))).status_code == 403
    assert (await ret(small, _approval(principal, "u-sam-r", "team_leader", team=("u-sam-r",)))).status_code == 403
    assert (await ret(small, _approval(principal, "u-tl", "team_leader", team=("u-sam-r",), via="pos"))).status_code == 403
    assert (await ret(small, _approval(principal, "u-tl", "team_leader", team=("u-sam-r",), minutes=-1))).status_code == 428
    # His team leader, within the KES 2,000 limit: done, and recorded.
    r = await ret(small, _approval(principal, "u-tl", "team_leader", team=("u-sam-r",)))
    assert r.status_code == 201, r.text
    # KES 3,000 is above a team leader's limit; the branch manager there can.
    r = await ret(big, _approval(principal, "u-tl", "team_leader", team=("u-sam-r",)))
    assert r.status_code == 403 and "limit" in r.json()["detail"]
    assert (await ret(big, _approval(principal, "u-bm", "branch_manager", locs=(EAST,)))).status_code == 403
    assert (await ret(big, _approval(principal, "u-bm", "branch_manager", locs=(WEST,)))).status_code == 201

    # A manager signed in themselves needs nobody.
    as_principal(admin)
    third = (await client.post("/pos/sales", json=sale(500))).json()
    assert (await ret(third, shift_id=None)).status_code == 201
