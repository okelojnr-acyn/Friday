"""Shared test fixtures for apps/minions. See friday_common/testing.py
for the harness this builds on.
"""

import asyncio
import os
from pathlib import Path

SCHEMA = "minions_test"
os.environ["DB_SCHEMA"] = SCHEMA

import pytest
from httpx import ASGITransport, AsyncClient

from friday_common.auth import get_current_principal
from friday_common.settings import get_settings
from friday_common.testing import dispose_engine, make_principal, prepare_test_schema

from app.main import app

APP_DIR = Path(__file__).parent


@pytest.fixture(scope="session", autouse=True)
def _migrated_schema():
    asyncio.run(prepare_test_schema(APP_DIR, SCHEMA))


@pytest.fixture
def principal():
    return make_principal()


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


@pytest.fixture
def kernel_auth_header():
    return {"Authorization": f"Bearer {get_settings().kernel_events_token}"}
