"""Parcels (plan 12.2; owner 2026-11-22: Guss scans them in and out)."""

import uuid
from dataclasses import replace

L1, L2 = str(uuid.uuid4()), str(uuid.uuid4())


async def test_scanning_a_parcel_in_out_and_delivered(client, as_principal, principal):
    depot = replace(principal, user_id="u-depot", email="depot@x.test", role="member", perms=("logistics",), locs=(L1,))
    driver = replace(principal, user_id="u-otieno", email="otieno@x.test", role="member", perms=("logistics",), locs=(L1,))
    other = replace(principal, user_id="u-other", email="other@x.test", role="member", perms=("logistics",), locs=(L2,))
    cashier = replace(principal, user_id="u-c", role="member", perms=("cashier",))

    scan = lambda code, action: client.post("/parcels/scan", json={"code": code, "action": action})  # noqa: E731

    as_principal(cashier)
    assert (await scan("WB-1", "in")).status_code == 403  # not logistics

    as_principal(depot)
    assert (await scan("WB-1", "out")).status_code == 404  # unknown: scan it in first
    r = await scan("WB-1", "in")  # an unknown code is booked in, with the depot
    assert r.status_code == 200 and r.json()["status"] == "received" and r.json()["holder_email"] == "depot@x.test"

    as_principal(driver)
    assert (await scan("WB-1", "delivered")).status_code == 403  # it's with the depot
    r = await scan("WB-1", "out")  # picking it up makes it his
    assert r.json()["status"] == "out_for_delivery" and r.json()["holder_email"] == "otieno@x.test"
    assert [p["tracking_code"] for p in (await client.get("/parcels")).json()] == ["WB-1"]
    assert (await scan("WB-1", "delivered")).json()["status"] == "delivered"
    assert (await scan("WB-1", "out")).status_code == 409  # delivered stays delivered

    # Staff see the parcels they hold; others at another location don't.
    as_principal(other)
    assert (await client.get("/parcels")).json() == []

    # The manager sees it all, with its history.
    as_principal(principal)
    parcel = (await client.get("/parcels?code=WB-1")).json()[0]
    history = (await client.get(f"/parcels/{parcel['id']}/events")).json()
    assert [(e["status"], e["by_email"]) for e in history] == [
        ("received", "depot@x.test"),
        ("out_for_delivery", "otieno@x.test"),
        ("delivered", "otieno@x.test"),
    ]
    # Booked in by hand, with its details; the same code twice is refused.
    made = await client.post("/parcels", json={"tracking_code": "WB-2", "recipient_name": "Amina", "destination": "Kisumu"})
    assert made.status_code == 201 and made.json()["recipient_name"] == "Amina"
    assert (await client.post("/parcels", json={"tracking_code": "WB-2"})).status_code == 409
    r = await client.patch(f"/parcels/{made.json()['id']}", json={"recipient_phone": "0712345678"})
    assert r.json()["recipient_phone"] == "0712345678"
