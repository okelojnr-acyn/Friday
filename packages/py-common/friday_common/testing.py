"""Shared pytest harness for every app service -- one way to stand up an
isolated test schema and a fake authenticated caller, instead of each
app's conftest.py reinventing both.

Usage (see apps/crm/conftest.py for the full pattern): set `DB_SCHEMA` to
a dedicated `<app>_test` schema *before* importing the app's FastAPI
instance (settings are read once, at import time), then call
`prepare_test_schema` from a session-scoped fixture before any test
hits the database.
"""

import os
import uuid
from pathlib import Path

from .auth import Principal
from .migrate import run_migrations


def test_dsn() -> str:
    """The asyncpg-flavored DSN `friday_common.migrate.run_migrations`
    needs -- same server tests run the app against (`DATABASE_URL`),
    just without the `+asyncpg` SQLAlchemy driver suffix."""
    dsn = os.environ.get("DATABASE_URL", "postgresql+asyncpg://friday:friday@localhost:5432/friday")
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


async def prepare_test_schema(app_dir: Path, schema: str) -> None:
    """Drop `schema` and replay every migration into it from scratch.
    Using a schema name distinct from the app's real one (by convention,
    `<app>_test`) means running the test suite never touches dev/prod
    data that happens to live on the same Postgres server, and starting
    from a drop means leftover rows from a previous run never leak into
    the next one.
    """
    import asyncpg

    dsn = test_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    finally:
        await conn.close()
    await run_migrations(dsn, schema, app_dir / "migrations")


async def dispose_engine() -> None:
    """Call after each test. `friday_common.db.make_engine()` is
    `@lru_cache`'d for the app's real lifetime -- one process, one event
    loop, so its pooled asyncpg connections are always used on the loop
    that created them. pytest-asyncio gives every test its own event
    loop, so a connection opened in test A's loop and reused in test B's
    (different) loop crashes on teardown -- reliably on Windows'
    ProactorEventLoop. Disposing and clearing the cache forces a fresh
    engine/connections on the next request, scoped to whichever loop is
    current.
    """
    from .db import make_engine

    await make_engine().dispose()
    make_engine.cache_clear()


def make_principal(org_id: str | None = None, role: str = "member", email: str = "test@example.com") -> Principal:
    """A fake authenticated caller for `app.dependency_overrides`. Tests
    override `get_current_principal` with this instead of minting a real
    JWT -- the thing worth testing is each app's own business logic and
    RLS boundary, not the kernel's token issuance (that's covered where
    the kernel itself is tested).
    """
    return Principal(
        user_id=str(uuid.uuid4()),
        org_id=org_id or str(uuid.uuid4()),
        role=role,
        email=email,
    )
