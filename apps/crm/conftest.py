"""Shared test fixtures for apps/crm. See friday_common/testing.py for the
harness this builds on, and README.md's "Before opening a PR" for how
`pytest apps/crm` is expected to be run (a real Postgres reachable via
DATABASE_URL, same as local dev).
"""

import asyncio
import os
from pathlib import Path

# Must happen before `from app.main import app` below -- FridaySettings
# reads DB_SCHEMA once, at that import's first call to get_settings().
# A dedicated "_test" schema keeps the suite from ever touching a
# dev/prod schema that happens to live on the same Postgres server.
SCHEMA = "crm_test"
os.environ["DB_SCHEMA"] = SCHEMA

import pytest
from httpx import ASGITransport, AsyncClient

from friday_common.auth import get_current_principal
from friday_common.testing import dispose_engine, make_principal, prepare_test_schema

from app.main import app

APP_DIR = Path(__file__).parent


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema():
    # A plain sync fixture running its own throwaway event loop, rather
    # than an async session-scoped fixture, so this never has to agree
    # with pytest-asyncio's per-test event loop scope.
    asyncio.run(prepare_test_schema(APP_DIR, SCHEMA))


@pytest.fixture
def principal():
    return make_principal()


@pytest.fixture
def as_principal():
    """Swap which Principal `get_current_principal` resolves to for the
    rest of the test -- the one hook every org-isolation test needs."""

    def _set(p):
        app.dependency_overrides[get_current_principal] = lambda: p

    return _set


@pytest.fixture(autouse=True)
def _default_principal(principal, as_principal):
    as_principal(principal)
    yield
    app.dependency_overrides.pop(get_current_principal, None)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
async def _dispose_engine_after_test():
    yield
    await dispose_engine()
