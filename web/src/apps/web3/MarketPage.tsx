import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { fetchMarketPrices, fetchTrending, type CoinPrice } from "../../lib/web3";
import { getIntegration, setIntegration } from "../../lib/integrations";
import { Card } from "../../ui/Card";
import { Button } from "../../ui/Button";
import { Input } from "../../ui/Field";
import { Icon } from "../../ui/Icon";

/** Web3's other mini-app, alongside the Acyn Wallet-backed Treasury one
 * (see TreasuryPage.tsx): live crypto prices and trending coins via
 * CoinGecko. No wallet, no API key, no "Connect" step required -- it
 * works with a sensible default watchlist out of the box; editing the
 * watchlist is the only thing that touches Settings > Integrations. */
export function MarketPage() {
  const [prices, setPrices] = useState<Record<string, CoinPrice> | null>(null);
  const [trending, setTrending] = useState<{ item: { id: string; name: string } }[]>([]);
  const [watchlistInput, setWatchlistInput] = useState("");
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function load() {
    fetchMarketPrices()
      .then(setPrices)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load prices"));
    fetchTrending()
      .then(setTrending)
      .catch(() => setTrending([]));
  }

  useEffect(load, []);

  async function openEditor() {
    setEditing(true);
    try {
      const cred = await getIntegration("coingecko");
      const watchlist = Array.isArray(cred.config.watchlist) ? (cred.config.watchlist as string[]) : [];
      setWatchlistInput(watchlist.join(", "));
    } catch {
      setWatchlistInput("");
    }
  }

  async function saveWatchlist() {
    const watchlist = watchlistInput
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      await setIntegration("coingecko", { watchlist });
      setEditing(false);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save watchlist");
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Market</h1>
          <nav style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Link to="/web3/treasury" className="btn btn-sm btn-pill btn-secondary">
              Treasury
            </Link>
            <Link to="/web3/wallet" className="btn btn-sm btn-pill btn-secondary">
              Wallets
            </Link>
            <Link to="/web3/transaction" className="btn btn-sm btn-pill btn-secondary">
              Transactions
            </Link>
            <span className="btn btn-sm btn-pill btn-primary">Market</span>
          </nav>
        </div>
        <Button size="sm" variant="secondary" onClick={openEditor}>
          Edit watchlist
        </Button>
      </div>

      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      {editing ? (
        <Card style={{ marginBottom: 16 }}>
          <div className="field-label" style={{ marginBottom: 8 }}>
            Coin ids, comma-separated (CoinGecko ids, e.g. bitcoin, ethereum, solana)
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Input value={watchlistInput} onChange={(e) => setWatchlistInput(e.target.value)} style={{ flex: 1 }} />
            <Button size="sm" variant="primary" onClick={saveWatchlist}>
              Save
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </Card>
      ) : null}

      <Card style={{ marginBottom: 16 }}>
        <div className="field-label" style={{ marginBottom: 10 }}>
          <Icon name="trend-up" size={13} /> Watched prices
        </div>
        {!prices ? (
          <div className="spinner">Loading...</div>
        ) : Object.keys(prices).length === 0 ? (
          <div className="empty-state">No coins watched yet -- edit the watchlist above.</div>
        ) : (
          Object.entries(prices).map(([coin, price]) => (
            <div key={coin} className="pos-totals-row">
              <span style={{ textTransform: "capitalize" }}>{coin}</span>
              <span>
                ${price.usd.toLocaleString()}
                {price.usd_24h_change !== undefined ? (
                  <span style={{ color: price.usd_24h_change >= 0 ? "var(--success)" : "var(--danger)", marginLeft: 8 }}>
                    {price.usd_24h_change >= 0 ? "+" : ""}
                    {price.usd_24h_change.toFixed(2)}%
                  </span>
                ) : null}
              </span>
            </div>
          ))
        )}
      </Card>

      <Card>
        <div className="field-label" style={{ marginBottom: 10 }}>
          Trending on CoinGecko
        </div>
        {trending.length === 0 ? (
          <div className="empty-state">Nothing to show right now.</div>
        ) : (
          trending.slice(0, 8).map((t) => (
            <div key={t.item.id} className="pos-totals-row">
              <span>{t.item.name}</span>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}
