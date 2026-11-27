"""Plan 20.3: when the cashier changes mid-shift the outgoing one counts the
drawer; each stretch carries its own over/short, so the next cashier never
inherits the last one's shortage."""

import pytest

from app.registers import handover_stretches

def test_each_stretch_carries_only_its_own_shortage():
    # A was 200 short at the first handover; B's drawer was then right
    # (still 200 short overall) -> B's stretch is 0, not -200.
    rows = [("a@x", 9_800, 10_000, "t1"), ("b@x", 14_800, 15_000, "t2"), ("c@x", 15_100, 15_000, "t3")]
    assert [s["short_cents"] for s in handover_stretches(rows)] == [-200, 0, 300]


@pytest.mark.usefixtures("a_till")
async def test_handover_records_the_count_on_the_open_shift(client):
    shift = (await client.post("/pos/shifts/open", json={"opening_float_cents": 10_000})).json()
    r = await client.post(f"/pos/shifts/{shift['id']}/handover", json={"counted_cents": 9_500})
    assert r.status_code == 200
    assert r.json()["expected_cents"] == 10_000 and r.json()["short_cents"] == -500

    closed = (await client.post(f"/pos/shifts/{shift['id']}/close", json={"closing_count_cents": 9_500})).json()
    assert [h["short_cents"] for h in closed["summary"]["handovers"]] == [-500]
    assert (await client.post(f"/pos/shifts/{shift['id']}/handover", json={"counted_cents": 1})).status_code == 400
