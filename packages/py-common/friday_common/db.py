from collections.abc import AsyncIterator
from functools import lru_cache
from uuid import uuid4

from fastapi import Depends
from sqlalchemy import URL, event, make_url, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .auth import Principal, get_current_principal
from .settings import FridaySettings, get_settings


def engine_args(database_url: str) -> tuple[URL, dict]:
    """Adapt a libpq-style DATABASE_URL for SQLAlchemy's asyncpg dialect.

    Friday Host hands out `...?sslmode=require` URLs pointing at PgBouncer
    in *transaction* pooling mode. Two things break with that, both found
    live on 2026-11-10 (every app query 500'd while migrations -- which
    use asyncpg.connect directly -- worked fine):

    - asyncpg's connect() has no `sslmode` kwarg (it's `ssl`), and the
      SQLAlchemy dialect passes URL query params straight through, so
      every connection raised `TypeError: ... 'sslmode'`.
    - asyncpg's named prepared-statement cache doesn't survive
      transaction pooling (the next transaction may land on a different
      server connection). Disabled per SQLAlchemy's documented PgBouncer
      recipe, with unique statement names so concurrent ones can't clash.
    """
    url = make_url(database_url)
    query = dict(url.query)
    connect_args: dict = {
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }
    sslmode = query.pop("sslmode", None)
    if sslmode:
        connect_args["ssl"] = sslmode  # asyncpg accepts libpq mode names
    query["prepared_statement_cache_size"] = "0"
    return url.set(query=query), connect_args


@lru_cache
def make_engine() -> AsyncEngine:
    settings = get_settings()
    url, connect_args = engine_args(settings.database_url)
    return create_async_engine(url, pool_pre_ping=True, connect_args=connect_args)


def _pin_per_transaction(session: AsyncSession, schema: str, org_id: str | None = None) -> None:
    """Apply search_path (and the RLS org context) at the start of *every*
    transaction this session opens, transaction-scoped (is_local=true).

    Why not a plain session-level `SET search_path` once (the original
    code): behind PgBouncer transaction pooling the session-level setting
    sticks to the pooled *server* connection and leaks into whichever
    app's transaction lands there next, while this session's own next
    transaction may land on a connection carrying some other app's
    search_path. Why not set it once transaction-locally: handlers commit
    mid-request and keep querying, and the setting dies with the first
    commit (CI caught exactly that, 2026-11-10: `relation "wallets" does
    not exist`). Re-applying on every begin is correct in both cases.
    """
    sp = f'"{schema}", public'

    @event.listens_for(session.sync_session, "after_begin")
    def _apply(_sess, _txn, connection) -> None:
        if schema != "public":
            connection.execute(text("SELECT set_config('search_path', :sp, true)"), {"sp": sp})
        if org_id is not None:
            connection.execute(
                text("SELECT set_config('app.current_org_id', :org_id, true)"), {"org_id": org_id}
            )


def _session_factory(settings: FridaySettings | None = None) -> async_sessionmaker[AsyncSession]:
    settings = settings or get_settings()
    return async_sessionmaker(make_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Sets `search_path` to this app's own Postgres
    schema for the lifetime of the session -- each app owns its tables,
    nobody reaches across into another app's schema directly. Cross-app
    reads go through that app's HTTP API or an event, never a raw join.
    """
    settings = get_settings()
    session_factory = _session_factory(settings)
    async with session_factory() as session:
        _pin_per_transaction(session, settings.db_schema)
        yield session


async def get_org_session(
    principal: Principal = Depends(get_current_principal),
) -> AsyncIterator[AsyncSession]:
    """The dependency every resource route should actually use. On top of
    what `get_session` does, this sets `app.current_org_id` for the
    transaction so each table's Row-Level Security policy enforces the org
    boundary in Postgres itself -- not just in a `WHERE org_id = ...` an
    engineer might forget to write. Belt and suspenders: queries should
    still filter by `principal.org_id` explicitly; RLS is the backstop.
    """
    settings = get_settings()
    session_factory = _session_factory(settings)
    async with session_factory() as session:
        _pin_per_transaction(session, settings.db_schema, principal.org_id)
        yield session


async def set_org_context(session: AsyncSession, org_id: str) -> None:
    """Set the RLS org context by hand -- for the rare code path that isn't
    a user request with a Principal (e.g. an inbound webhook from the
    kernel, which carries a trusted org_id straight from the event body
    instead of a JWT).

    Postgres's `SET`/`SET LOCAL` don't accept bound parameters (`SET LOCAL
    x = $1` is a syntax error) -- `set_config(name, value, is_local)` is
    the parameterized equivalent, with `is_local=true` matching `SET
    LOCAL`'s transaction-scoped lifetime.
    """
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"), {"org_id": org_id}
    )
