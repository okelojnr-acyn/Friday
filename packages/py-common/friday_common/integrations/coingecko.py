"""CoinGecko adapter -- code-ready, and the one integration in this
package that needs no credential at all to work: the free public API
(https://api.coingecko.com/api/v3) has no key requirement, rate-limited
generously enough for "a few coins' prices on a dashboard panel." `config`
is entirely optional here -- an org's `coingecko` config is really just a
`watchlist` preference (which coins to show), not a secret, plus an
optional `api_key` for CoinGecko's paid Pro tier (higher rate limits, a
different base URL) if a deployment ever needs it.

Used by apps/web3's Market mini-app (see
`apps/web3/app/main.py`'s `/market/*` routes) -- Web3's other mini-app
alongside the Acyn Wallet-backed Treasury one; see ARCHITECTURE.md's
"Integrations" section for why Web3 isn't just a wallet.
"""

import httpx

from .base import MarketDataProvider

PUBLIC_API_BASE = "https://api.coingecko.com/api/v3"
PRO_API_BASE = "https://pro-api.coingecko.com/api/v3"

DEFAULT_WATCHLIST = ["bitcoin", "ethereum", "solana"]


class CoinGeckoProvider(MarketDataProvider):
    def __init__(self, config: dict | None = None):
        config = config or {}
        self.api_key = config.get("api_key", "")
        self.base_url = PRO_API_BASE if self.api_key else PUBLIC_API_BASE
        self.watchlist: list[str] = config.get("watchlist") or DEFAULT_WATCHLIST

    def _headers(self) -> dict:
        return {"x-cg-pro-api-key": self.api_key} if self.api_key else {}

    async def get_prices(self, coin_ids: list[str], vs_currency: str = "usd") -> dict:
        async with httpx.AsyncClient(timeout=10.0, base_url=self.base_url) as client:
            resp = await client.get(
                "/simple/price",
                params={
                    "ids": ",".join(coin_ids),
                    "vs_currencies": vs_currency,
                    "include_24hr_change": "true",
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    async def get_trending(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=10.0, base_url=self.base_url) as client:
            resp = await client.get("/search/trending", headers=self._headers())
            resp.raise_for_status()
            return resp.json().get("coins", [])
