from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .auth import Principal, get_current_principal
from .settings import FridaySettings, get_settings


@lru_cache
def make_engine() -> AsyncEngine:
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


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
        if settings.db_schema != "public":
            await session.execute(text(f'SET search_path TO "{settings.db_schema}", public'))
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
        if settings.db_schema != "public":
            await session.execute(text(f'SET search_path TO "{settings.db_schema}", public'))
        await set_org_context(session, principal.org_id)
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
