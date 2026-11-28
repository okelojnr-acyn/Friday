"""Shared test fixtures for apps/web3. See friday_common/testing.py for
the harness this builds on.
"""

import asyncio
import os
from pathlib import Path

SCHEMA = "web3_test"
os.environ["DB_SCHEMA"] = SCHEMA

import pytest
from friday_common.auth import get_current_principal
from friday_common.testing import dispose_engine, make_principal, prepare_test_schema
from httpx import ASGITransport, AsyncClient

from app.main import app

APP_DIR = Path(__file__).parent


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema():
    asyncio.run(prepare_test_schema(APP_DIR, SCHEMA))


@pytest.fixture
def principal():
    # An admin by default: these tests check business logic; who may do
    # what (plan section 12) is in tests/test_roles.py.
    return make_principal(role="admin")


@pytest.fixture
def as_principal():
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


@pytest.fixture(autouse=True)
def _integrations_not_connected(monkeypatch):
    """No kernel in tests: every provider reads as not connected unless a
    test patches get_integration_config itself."""

    async def not_connected(org_id, provider):
        return {}

    monkeypatch.setattr("friday_common.integrations.config._fetch", not_connected)
