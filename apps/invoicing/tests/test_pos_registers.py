"""Registers and their shifts (owner, 2026-11-15): several tills at once,
expected cash per till, a sale recorded once however often it's resent."""

import time
import uuid
from dataclasses import replace


def sale(amount, method="cash", shift_id=None, client_sale_id=None, created_at_ms=None):
    body = {
        "lines": [{"description": "Item", "quantity": 1, "unit_price_cents": amount}],
        "amount_cents": amount,
        "method": method,
        "client_sale_id": client_sale_id or str(uuid.uuid4()),
    }
    if shift_id:
        body["shift_id"] = shift_id
    if created_at_ms:
        body["created_at_ms"] = created_at_ms
    return body


async def make_registers(client, as_principal, principal, *names):
    as_principal(replace(principal, role="admin"))
    ids = []
    for n in names:
        r = await client.post("/pos/registers", json={"name": n, "location_name": "Westlands"})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    as_principal(principal)
    return ids


async def test_two_tills_open_at_once_and_count_only_their_own_cash(client, as_principal, principal):
    till1, till2 = await make_registers(client, as_principal, principal, "Till 1", "Till 2")
    s1 = (await client.post("/pos/shifts/open", json={"register_id": till1, "opening_float_cents": 500000})).json()
    s2 = (await client.post("/pos/shifts/open", json={"register_id": till2, "opening_float_cents": 200000})).json()
    assert s1["register_id"] == till1 and s2["register_id"] == till2

    await client.post("/pos/sales", json=sale(1000, "cash", s1["id"]))
    await client.post("/pos/sales", json=sale(2500, "cash", s2["id"]))
    await client.post("/pos/sales", json=sale(4000, "mpesa", s1["id"]))

    closed = (await client.post(f"/pos/shifts/{s1['id']}/close", json={"closing_count_cents": 500900})).json()
    assert closed["expected_cents"] == 501000  # float + till 1's cash only
    assert closed["closing_count_cents"] == 500900
    assert closed["summary"]["by_method"]["mpesa"]["cents"] == 4000
    assert closed["summary"]["sales"] == 2
    assert closed["closed_by_email"] == principal.email

    # Till 2 is still open, and its own count is separate.
    regs = {r["id"]: r for r in (await client.get("/pos/registers")).json()}
    assert regs[till1]["open_shift"] is None
    assert regs[till2]["open_shift"]["id"] == s2["id"]


async def test_a_register_opens_once(client, as_principal, principal):
    (till,) = await make_registers(client, as_principal, principal, "Till A")
    first = await client.post("/pos/shifts/open", json={"register_id": till, "opening_float_cents": 0})
    again = await client.post("/pos/shifts/open", json={"register_id": till, "opening_float_cents": 0})
    assert first.status_code == 201 and again.status_code == 409


async def test_a_resent_sale_is_recorded_once(client):
    body = sale(1500, client_sale_id="till-1-sale-77")
    first = await client.post("/pos/sales", json=body)
    again = await client.post("/pos/sales", json=body)
    assert first.status_code == 201 and again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    numbers = [i["number"] for i in (await client.get("/invoices")).json() if i["number"].startswith("POS-")]
    assert len(numbers) == 1


async def test_an_offline_sale_keeps_its_own_time(client):
    two_hours_ago = int((time.time() - 7200) * 1000)
    inv = (await client.post("/pos/sales", json=sale(700, created_at_ms=two_hours_ago))).json()
    issued = inv["created_at"]
    assert issued is not None
    from datetime import datetime

    t = datetime.fromisoformat(issued.replace("Z", "+00:00")).timestamp()
    assert abs(t - two_hours_ago / 1000) < 2
    # A time in the far future is ignored.
    future = int((time.time() + 86400) * 1000)
    inv = (await client.post("/pos/sales", json=sale(700, created_at_ms=future))).json()
    t = datetime.fromisoformat(inv["created_at"].replace("Z", "+00:00")).timestamp()
    assert t <= time.time() + 1


async def test_a_return_at_the_till_comes_out_of_the_drawer(client, a_till):
    shift = (await client.post("/pos/shifts/open", json={"opening_float_cents": 10000})).json()
    sold = (await client.post("/pos/sales", json=sale(3000, "cash", shift["id"]))).json()
    ret = await client.post(f"/pos/sales/{sold['number']}/return?shift_id={shift['id']}")
    assert ret.status_code == 201, ret.text
    closed = (await client.post(f"/pos/shifts/{shift['id']}/close", json={"closing_count_cents": 10000})).json()
    assert closed["expected_cents"] == 10000
    assert closed["summary"]["returns"] == 1


async def test_only_admins_make_registers_and_a_shift_from_elsewhere_is_refused(client, as_principal, principal):
    assert (await client.post("/pos/registers", json={"name": "Sneaky"})).status_code == 403
    r = await client.post("/pos/sales", json=sale(100, shift_id=str(uuid.uuid4())))
    assert r.status_code == 422


async def test_the_till_never_makes_up_a_register(client, as_principal, principal):
    # No tills set up: opening is refused with where to add one.
    r = await client.post("/pos/shifts/open", json={"opening_float_cents": 0})
    assert r.status_code == 400 and "Business settings" in r.json()["detail"]
    assert (await client.get("/pos/registers")).json() == []


async def test_a_one_till_shop_needs_no_choice(client, as_principal, principal):
    # One till set up: a request naming none uses it, and an old till
    # build's sale (no shift_id) joins its open shift.
    await make_registers(client, as_principal, principal, "Till 1")
    shift = (await client.post("/pos/shifts/open", json={"opening_float_cents": 0})).json()
    await client.post("/pos/sales", json=sale(900, "cash"))
    regs = (await client.get("/pos/registers")).json()
    assert [r["name"] for r in regs] == ["Till 1"]
    closed = (await client.post(f"/pos/shifts/{shift['id']}/close", json={"closing_count_cents": 900})).json()
    assert closed["expected_cents"] == 900


async def test_a_receipt_number_finds_the_sale(client):
    sold = (await client.post("/pos/sales", json=sale(1200, client_sale_id="ab12cd34-0000-4000-8000-000000000001"))).json()
    found = await client.get("/pos/sales/AB12CD34")
    assert found.status_code == 200 and found.json()["id"] == sold["id"]
    assert (await client.get("/pos/sales/AB12")).status_code == 404  # too short to be a receipt
