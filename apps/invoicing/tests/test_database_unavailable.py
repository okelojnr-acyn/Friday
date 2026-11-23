"""A request that can't reach the database gets a 503 to retry, not a 500
with a traceback; other database errors are untouched."""

import httpx
import pytest
from sqlalchemy import exc as sa_exc

from friday_common.app_factory import create_app


@pytest.fixture
def app():
    app = create_app("friday-test")

    @app.get("/down")
    async def down():
        raise sa_exc.OperationalError("SELECT 1", {}, ConnectionRefusedError("the database system is shutting down"))

    @app.get("/duplicate")
    async def duplicate():
        raise sa_exc.IntegrityError("INSERT", {}, Exception("duplicate key"))

    return app


async def test_database_out_of_reach_is_a_503_to_retry(app):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/down")
        assert r.status_code == 503 and r.headers["retry-after"] == "5"
        assert (await c.get("/duplicate")).status_code == 500
