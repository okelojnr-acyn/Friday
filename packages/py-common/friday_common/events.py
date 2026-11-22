import asyncio
import json
import logging
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import text
from fastapi import Header, HTTPException, status

from .settings import get_settings

logger = logging.getLogger("friday.events")


class EventIn:
    """Shape of an event the kernel forwards to a subscriber's webhook."""

    def __init__(self, type: str, org_id: str, payload: dict):
        self.type = type
        self.org_id = org_id
        self.payload = payload


def require_kernel_token(authorization: str | None = Header(default=None)) -> None:
    """Dependency for an app's inbound webhook routes: verifies the call
    actually came from the kernel's event dispatcher, using the same
    shared token `publish_event` sends out with."""
    settings = get_settings()
    expected = f"Bearer {settings.kernel_events_token}"
    if authorization != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid kernel token")


async def _send(client: httpx.AsyncClient, event_id: str, event_type: str, org_id: str, payload: dict) -> None:
    settings = get_settings()
    resp = await client.post(
        f"{settings.kernel_internal_url}/events",
        json={"id": event_id, "type": event_type, "org_id": org_id, "payload": payload},
        headers={"Authorization": f"Bearer {settings.kernel_events_token}"},
    )
    resp.raise_for_status()


def _backoff(attempts: int) -> timedelta:
    """5 s, 10 s, 20 s ... up to an hour between tries."""
    return timedelta(seconds=min(5 * 2 ** max(attempts - 1, 0), 3600))


def _outbox() -> str:
    return f'"{get_settings().db_schema}".event_outbox'


# Deliveries started after a commit; kept so they aren't garbage-collected.
_sending: set = set()


async def _stage(session, event_type: str, org_id: str, payload: dict) -> None:
    """Write the event in the caller's transaction and send it once that
    commits. A rollback drops the event with the change it describes."""
    from sqlalchemy import event as sa_event

    event_id = str(uuid.uuid4())
    await session.execute(
        text(f"INSERT INTO {_outbox()} (id, type, org_id, payload) VALUES (:id, :type, :org, CAST(:payload AS jsonb))"),
        {"id": event_id, "type": event_type, "org": org_id, "payload": json.dumps(payload, default=str)},
    )

    def _after_commit(_sync_session) -> None:
        try:
            task = asyncio.get_event_loop().create_task(deliver_due(only_id=event_id))
            _sending.add(task)
            task.add_done_callback(_sending.discard)
        except RuntimeError:
            pass  # no loop here: run_outbox sends it within its interval

    sa_event.listen(session.sync_session, "after_commit", _after_commit, once=True)


async def publish_event(event_type: str, org_id: str, payload: dict, *, session=None) -> None:
    """Publish a domain event (e.g. "invoicing.pos_sale.recorded") to the
    kernel, which delivers it to every app subscribed to it.

    Written to this app's outbox first, then sent; if the kernel can't be
    reached the outbox loop (run_outbox) keeps retrying with backoff, so a
    hiccup never loses a sale's stock or journal update (plan section 13,
    2026-11-16; before this a failed send was only logged). The event id
    travels with it, so a receiver that gets it twice can tell
    (first_delivery). Never raises: the request that published has
    already succeeded.

    With `session` (plan 19.2): the event is written in that session's
    transaction, before its commit, so a sale and the events it causes are
    saved together or not at all (before, a crash between the commit and
    this write lost the stock move or journal entry). Call it before
    `commit()`. Without `session` it keeps the after-commit behaviour.
    """
    if session is not None:
        await _stage(session, event_type, org_id, payload)
        return

    from .db import make_engine

    event_id = str(uuid.uuid4())
    try:
        async with make_engine().begin() as conn:
            await conn.execute(
                text(f"INSERT INTO {_outbox()} (id, type, org_id, payload) VALUES (:id, :type, :org, CAST(:payload AS jsonb))"),
                {"id": event_id, "type": event_type, "org": org_id, "payload": json.dumps(payload, default=str)},
            )
    except Exception as exc:  # noqa: BLE001 -- the outbox itself is unreachable
        logger.error("event %s: could not write the outbox (%s); sending once without it", event_type, exc)
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await _send(client, event_id, event_type, org_id, payload)
        except httpx.HTTPError as send_exc:
            logger.error("event %s lost: %s", event_type, send_exc)
        return
    await deliver_due(only_id=event_id)


async def deliver_due(only_id: str | None = None, limit: int = 50) -> int:
    """Sends due outbox events. Each is leased for a minute while it's
    being sent, so two workers (or a worker and publish_event) never send
    the same one at once. Returns how many were delivered."""
    from .db import make_engine

    engine = make_engine()
    where = "id = :only" if only_id else "delivered_at IS NULL AND next_attempt_at <= now()"
    try:
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        f"""UPDATE {_outbox()} SET next_attempt_at = now() + interval '1 minute', attempts = attempts + 1
                        WHERE id IN (SELECT id FROM {_outbox()} WHERE {where} AND delivered_at IS NULL
                                     ORDER BY created_at LIMIT :limit FOR UPDATE SKIP LOCKED)
                        RETURNING id, type, org_id, payload, attempts"""
                    ),
                    {"only": only_id, "limit": limit},
                )
            ).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning("outbox: could not read due events: %s", exc)
        return 0
    delivered = 0
    async with httpx.AsyncClient(timeout=5.0) as client:
        for row in rows:
            payload = row.payload if isinstance(row.payload, dict) else json.loads(row.payload)
            try:
                await _send(client, str(row.id), row.type, str(row.org_id), payload)
                outcome = ("delivered_at = now(), last_error = ''", {})
                delivered += 1
            except httpx.HTTPError as exc:
                logger.warning("event %s (%s) not delivered, try %d: %s", row.type, row.id, row.attempts, exc)
                outcome = (
                    "next_attempt_at = now() + :wait, last_error = :err",
                    {"wait": _backoff(row.attempts), "err": str(exc)[:500]},
                )
            try:
                async with engine.begin() as conn:
                    await conn.execute(text(f"UPDATE {_outbox()} SET {outcome[0]} WHERE id = :id"), {"id": row.id, **outcome[1]})
            except Exception as exc:  # noqa: BLE001
                logger.warning("outbox: could not record the outcome for %s: %s", row.id, exc)
    return delivered


async def run_outbox(interval_seconds: float = 10.0) -> None:
    """Background loop (started by create_app): sends whatever is due, and
    drops delivered events after a week."""
    from .db import make_engine

    last_trim = 0.0
    while True:
        try:
            while await deliver_due() > 0:
                pass
            now = asyncio.get_running_loop().time()
            if now - last_trim > 3600:
                async with make_engine().begin() as conn:
                    await conn.execute(
                        text(f"DELETE FROM {_outbox()} WHERE delivered_at < now() - interval '7 days'")
                    )
                last_trim = now
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 -- keep the loop alive
            logger.warning("outbox loop: %s", exc)
        await asyncio.sleep(interval_seconds)


async def first_delivery(session, body: dict) -> bool:
    """For a webhook handler, inside its own transaction: True the first
    time this event id arrives, False for a repeat (the kernel retries
    until a delivery succeeds, so a repeat is normal). Rolls back with the
    handler, so a failed handling is retried, not skipped. Events from an
    older kernel carry no id and are always handled."""
    event_id = body.get("id")
    if not event_id:
        return True
    row = (
        await session.execute(
            text("INSERT INTO processed_events (event_id) VALUES (:id) ON CONFLICT DO NOTHING RETURNING event_id"),
            {"id": str(event_id)},
        )
    ).first()
    return row is not None
