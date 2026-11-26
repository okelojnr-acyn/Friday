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
def _no_reporting_line(monkeypatch):
    """No kernel in tests: nobody up the line and the default limits (what
    approvers_for answers when the kernel can't). Tests that need a line
    patch app.main.approvers_for themselves."""
    from friday_common.access import APPROVAL_LIMIT_CENTS, Approvers

    async def none(_org, _user):
        return Approvers(limits=dict(APPROVAL_LIMIT_CENTS), chain=(), top=())

    monkeypatch.setattr("app.main.approvers_for", none)


@pytest.fixture(autouse=True)
def _receipts_not_checked(monkeypatch):
    """No kernel in tests: the Standard spending policy. Claim tests that
    aren't about receipts approve without one; test_claim_what_for.py
    puts the real receipt rule back. Spends never need asking first here
    either."""
    from friday_common.access import STANDARD_SPENDING

    async def standard(_org):
        # Asking first is off too (test_spend_requests.py puts it back).
        never = 10**12
        return {**STANDARD_SPENDING, "ask_first_member": never, "ask_first_team_leader": never, "ask_first_branch_manager": never}

    async def fine(_session, _claim):
        return None

    monkeypatch.setattr("app.main.spending_policy", standard)
    monkeypatch.setattr("app.main._receipt_problem", fine)


@pytest.fixture(autouse=True)
async def _dispose_engine_after_test():
    yield
    await dispose_engine()


@pytest.fixture
def kernel_auth_header():
    return {"Authorization": f"Bearer {get_settings().kernel_events_token}"}
