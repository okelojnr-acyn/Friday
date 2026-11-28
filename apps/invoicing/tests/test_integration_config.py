"""get_integration_config: "not connected" is {}, a kernel that can't be
reached is an error (a 503 to retry), and a connected config is reused
for a minute instead of asking the kernel on every call."""

import httpx
import pytest

from friday_common.app_factory import create_app
from friday_common.integrations import config as cfg


@pytest.fixture(autouse=True)
def _integrations_not_connected():
    """Overrides conftest's: these tests use the real kernel call."""


@pytest.fixture
def kernel(monkeypatch):
    calls = []
    real = httpx.AsyncClient

    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/down"):
            return httpx.Response(502)
        if request.url.path.endswith("/none"):
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"secret_key": "sk_test"})

    monkeypatch.setattr(cfg, "_cache", {})
    monkeypatch.setattr(cfg.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    return calls


async def test_not_connected_is_empty_and_a_kernel_blip_is_an_error(kernel):
    assert await cfg.get_integration_config("org", "none") == {}
    with pytest.raises(cfg.IntegrationConfigUnavailable):
        await cfg.get_integration_config("org", "down")


async def test_a_connected_config_is_reused_for_a_minute(kernel, monkeypatch):
    first = await cfg.get_integration_config("org", "paystack")
    first["secret_key"] = "changed by a caller"
    assert await cfg.get_integration_config("org", "paystack") == {"secret_key": "sk_test"}
    assert kernel.count("/internal/integrations/org/paystack") == 1
    # "Not connected" isn't kept: a key pasted now works at once.
    await cfg.get_integration_config("org", "none")
    await cfg.get_integration_config("org", "none")
    assert kernel.count("/internal/integrations/org/none") == 2
    # After the minute it asks again.
    monkeypatch.setattr(cfg, "CACHE_SECONDS", -1)
    monkeypatch.setattr(cfg, "_cache", {})
    await cfg.get_integration_config("org", "paystack")
    await cfg.get_integration_config("org", "paystack")
    assert kernel.count("/internal/integrations/org/paystack") == 3


async def test_settings_out_of_reach_is_a_503_to_retry():
    app = create_app("friday-test")

    @app.get("/pay")
    async def pay():
        raise cfg.IntegrationConfigUnavailable("couldn't reach settings for paystack; try again")

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/pay")
    assert r.status_code == 503 and r.headers["retry-after"] == "5"
    assert "try again" in r.json()["error"]
