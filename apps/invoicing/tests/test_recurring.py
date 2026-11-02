from datetime import UTC, datetime

from app.main import _advance


def test_advance_weekly():
    assert _advance(datetime(2026, 1, 1, tzinfo=UTC), "weekly") == datetime(2026, 1, 8, tzinfo=UTC)


def test_advance_monthly_clamps_to_28_for_month_end_templates():
    assert _advance(datetime(2026, 1, 31, tzinfo=UTC), "monthly") == datetime(2026, 2, 28, tzinfo=UTC)


def test_advance_monthly_rolls_into_next_year():
    assert _advance(datetime(2026, 12, 15, tzinfo=UTC), "monthly") == datetime(2027, 1, 15, tzinfo=UTC)


def test_advance_yearly():
    assert _advance(datetime(2026, 3, 10, tzinfo=UTC), "yearly") == datetime(2027, 3, 10, tzinfo=UTC)


async def test_create_invoice_with_recurring_interval_sets_next_recurrence(client):
    inv = (
        await client.post(
            "/invoices",
            json={
                "recurring_interval": "monthly",
                "lines": [{"description": "Retainer", "quantity": 1, "unit_price_cents": 10000}],
            },
        )
    ).json()
    assert inv["recurring_interval"] == "monthly"
    assert inv["next_recurrence_at"] is not None


async def test_create_invoice_defaults_to_not_recurring(client):
    inv = (await client.post("/invoices", json={})).json()
    assert inv["recurring_interval"] == ""
    assert inv["next_recurrence_at"] is None


async def test_create_invoice_rejects_invalid_recurring_interval(client):
    resp = await client.post("/invoices", json={"recurring_interval": "daily"})
    assert resp.status_code == 422


async def test_generate_recurring_invoices_is_a_noop_when_nothing_is_due(client):
    """A freshly created recurring template's next_recurrence_at is always
    in the future (see _advance's unit tests above) -- generate-recurring
    should clone nothing for it yet. The "actually due" path is exercised
    by _advance's own unit tests plus the clone logic reusing the exact
    same InvoiceLine-copy code path create_invoice already has test
    coverage for."""
    await client.post(
        "/invoices",
        json={
            "recurring_interval": "weekly",
            "lines": [{"description": "Retainer", "quantity": 1, "unit_price_cents": 5000}],
        },
    )
    resp = await client.post("/invoices/generate-recurring")
    assert resp.status_code == 200
    assert resp.json() == []
