"""Roadmap item 4: a till sale keeps who approved its price cut or big
discount (the till asks a leader's or manager's PIN first)."""

async def test_the_approver_is_kept_on_the_sale(client):
    resp = await client.post(
        "/pos/sales",
        json={
            "lines": [{"description": "Rice", "quantity": 1, "unit_price_cents": 40_000, "discount_bp": 0}],
            "amount_cents": 40_000,
            "method": "cash",
            "override_approved_by": "manager@shop.test",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["override_approved_by"] == "manager@shop.test"
