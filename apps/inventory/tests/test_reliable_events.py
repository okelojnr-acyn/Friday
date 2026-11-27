"""Events survive a kernel hiccup and a repeat is applied once (plan
section 13, 2026-11-16). Lives under inventory because CI runs pytest per
app; it tests friday_common.events."""

from sqlalchemy import text

from friday_common import events
from friday_common.db import make_engine
from friday_common.settings import get_settings


async def outbox_rows():
    async with make_engine().begin() as conn:
        return (
            await conn.execute(
                text(f'SELECT type, attempts, delivered_at, last_error, next_attempt_at > now() AS later FROM "{get_settings().db_schema}".event_outbox ORDER BY created_at')
            )
        ).all()


async def test_an_event_the_kernel_misses_waits_in_the_outbox_then_goes(monkeypatch, principal):
    async with make_engine().begin() as conn:
        await conn.execute(text(f'DELETE FROM "{get_settings().db_schema}".event_outbox'))

    async def down(*args, **kwargs):
        raise events.httpx.ConnectError("kernel is restarting")

    monkeypatch.setattr(events, "_send", down)
    await events.publish_event("test.sale", principal.org_id, {"n": 1})
    (row,) = await outbox_rows()
    assert row.delivered_at is None and row.attempts == 1 and "restarting" in row.last_error and row.later

    sent = []

    async def up(client, event_id, event_type, org_id, payload):
        sent.append((event_id, event_type, payload))

    monkeypatch.setattr(events, "_send", up)
    async with make_engine().begin() as conn:  # the wait is over
        await conn.execute(text(f'UPDATE "{get_settings().db_schema}".event_outbox SET next_attempt_at = now()'))
    assert await events.deliver_due() == 1
    (row,) = await outbox_rows()
    assert row.delivered_at is not None and row.last_error == ""
    assert sent[0][1] == "test.sale" and sent[0][2] == {"n": 1}
    assert await events.deliver_due() == 0  # nothing sent twice


async def test_a_repeated_event_is_applied_once(client, kernel_auth_header, principal):
    p = (await client.post("/products", json={"name": "Flour", "price_cents": 21000, "on_hand_qty": 10})).json()
    for number in ("POS-A", "POS-B"):  # same event id, as a retry would send it
        await client.post(
            "/internal/webhooks/pos-sale",
            headers=kernel_auth_header,
            json={
                "id": "evt-123",
                "org_id": principal.org_id,
                "payload": {"invoice_number": number, "lines": [{"product_id": p["id"], "quantity": 1}]},
            },
        )
    assert (await client.get(f"/products/{p['id']}")).json()["on_hand_qty"] == 9


async def test_an_event_saved_with_its_change_commits_and_rolls_back_with_it(monkeypatch, principal):
    """Plan 19.2: published with `session=`, the event is written in the
    caller's transaction: a rollback leaves neither the change nor the
    event; a commit keeps both and sends the event right after."""
    from sqlalchemy.ext.asyncio import AsyncSession

    async with make_engine().begin() as conn:
        await conn.execute(text(f'DELETE FROM "{get_settings().db_schema}".event_outbox'))
    sent = []

    async def up(client, event_id, event_type, org_id, payload):
        sent.append(event_type)

    monkeypatch.setattr(events, "_send", up)

    async with AsyncSession(make_engine()) as session:
        await events.publish_event("test.rolled_back", principal.org_id, {"n": 1}, session=session)
        await session.rollback()
    assert await outbox_rows() == []

    async with AsyncSession(make_engine()) as session:
        await events.publish_event("test.committed", principal.org_id, {"n": 2}, session=session)
        assert sent == []  # nothing goes out before the commit
        await session.commit()
    import asyncio

    # The after-commit send runs as a task, and marks the row delivered
    # only after the send returns: wait for that, not just the send.
    for _ in range(100):
        rows = await outbox_rows()
        if rows and rows[0].delivered_at is not None:
            break
        await asyncio.sleep(0.02)
    (row,) = await outbox_rows()
    assert row.type == "test.committed" and row.delivered_at is not None
    assert sent == ["test.committed"]
