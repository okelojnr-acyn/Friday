"""apps/web3's Market mini-app -- never hits the real CoinGecko API,
CoinGeckoProvider is monkeypatched the same way AcynWalletProvider is in
test_wallets.py.
"""

from app import main


class FakeCoinGecko:
    def __init__(self, config):
        self.config = config
        self.watchlist = (config or {}).get("watchlist") or ["bitcoin", "ethereum", "solana"]

    async def get_prices(self, coin_ids):
        return {coin: {"usd": 100, "usd_24h_change": 1.5} for coin in coin_ids}

    async def get_trending(self):
        return [{"item": {"id": "dogwifhat", "name": "dogwifhat"}}]


async def _empty_config(org_id, provider):
    return {}


def _patch(monkeypatch, config=None):
    async def fake_config(org_id, provider):
        return config or {}

    monkeypatch.setattr(main, "get_integration_config", fake_config)
    monkeypatch.setattr(main, "CoinGeckoProvider", FakeCoinGecko)


async def test_market_prices_uses_default_watchlist_when_unconfigured(client, monkeypatch):
    _patch(monkeypatch)
    resp = await client.get("/market/prices")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"bitcoin", "ethereum", "solana"}


async def test_market_prices_honors_explicit_ids(client, monkeypatch):
    _patch(monkeypatch)
    resp = await client.get("/market/prices", params={"ids": "dogecoin,cardano"})
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"dogecoin", "cardano"}


async def test_market_prices_uses_saved_watchlist(client, monkeypatch):
    _patch(monkeypatch, config={"watchlist": ["pepe"]})
    resp = await client.get("/market/prices")
    assert resp.status_code == 200
    assert set(resp.json().keys()) == {"pepe"}


async def test_market_trending(client, monkeypatch):
    _patch(monkeypatch)
    resp = await client.get("/market/trending")
    assert resp.status_code == 200
    assert resp.json()[0]["item"]["id"] == "dogwifhat"


async def test_market_does_not_require_a_connected_provider(client, monkeypatch):
    monkeypatch.setattr(main, "get_integration_config", _empty_config)
    monkeypatch.setattr(main, "CoinGeckoProvider", FakeCoinGecko)
    resp = await client.get("/market/prices")
    assert resp.status_code == 200
