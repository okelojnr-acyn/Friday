import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { getIntegration, setIntegration } from "../../lib/integrations";
import {
  fetchTransactions,
  fetchWallets,
  refreshTransactionStatus,
  refreshWallets,
  requestPayout,
  type Transaction,
  type Wallet,
} from "../../lib/web3";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { FieldWrap, Input } from "../../ui/Field";
import { Badge, statusTone } from "../../ui/Badge";
import { Icon } from "../../ui/Icon";

/** The one hand-written screen in apps/web3 (same justification as the
 * POS register and Invoicing's "New Invoice" -- see ARCHITECTURE.md):
 * connecting a provider and requesting a payout aren't CRUD forms, so
 * they don't go through the generic ResourceSpec renderer. The raw
 * Wallet/Transaction lists are still reachable at /web3/wallet and
 * /web3/transaction through the normal schema-driven screens. */
export function TreasuryPage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [connecting, setConnecting] = useState(false);

  const [wallets, setWallets] = useState<Wallet[]>([]);
  const [transactions, setTransactions] = useState<Transaction[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [toAddress, setToAddress] = useState("");
  const [amount, setAmount] = useState("");
  const [currency, setCurrency] = useState("ETH");
  const [network, setNetwork] = useState("");
  const [reason, setReason] = useState("");
  const [submittingPayout, setSubmittingPayout] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getIntegration("acyn_wallet")
      .then((cred) => setConnected(cred.connected))
      .catch(() => setConnected(false));
    fetchWallets().then(setWallets).catch(() => setWallets([]));
    fetchTransactions().then(setTransactions).catch(() => setTransactions([]));
  }, []);

  async function connect() {
    if (!apiKey.trim()) return;
    setConnecting(true);
    setError(null);
    try {
      await setIntegration("acyn_wallet", { api_key: apiKey.trim() });
      setConnected(true);
      setApiKey("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not connect Acyn Wallet");
    } finally {
      setConnecting(false);
    }
  }

  async function doRefreshWallets() {
    setRefreshing(true);
    setError(null);
    try {
      setWallets(await refreshWallets());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not refresh balances");
    } finally {
      setRefreshing(false);
    }
  }

  async function submitPayout() {
    if (!toAddress.trim() || !amount.trim() || !network.trim()) {
      setError("To address, amount, and network are required");
      return;
    }
    setSubmittingPayout(true);
    setError(null);
    try {
      const txn = await requestPayout({ to_address: toAddress.trim(), currency, amount: amount.trim(), network: network.trim(), reason });
      setTransactions((cur) => [txn, ...cur]);
      setToAddress("");
      setAmount("");
      setReason("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not request payout");
    } finally {
      setSubmittingPayout(false);
    }
  }

  async function pollStatus(id: string) {
    try {
      const updated = await refreshTransactionStatus(id);
      setTransactions((cur) => cur.map((t) => (t.id === id ? updated : t)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not refresh status");
    }
  }

  async function copyAddress(address: string) {
    await navigator.clipboard.writeText(address);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  const receiveAddress = wallets[0]?.address || "";

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Treasury</h1>
          <nav style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Link to="/web3/wallet" className="btn btn-sm btn-pill btn-secondary">
              Wallets
            </Link>
            <Link to="/web3/transaction" className="btn btn-sm btn-pill btn-secondary">
              Transactions
            </Link>
            <Link to="/web3/market" className="btn btn-sm btn-pill btn-secondary">
              Market
            </Link>
          </nav>
        </div>
      </div>

      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      {connected === false ? (
        <Card style={{ marginBottom: 16 }}>
          <div className="field-label" style={{ marginBottom: 8 }}>
            <Icon name="key" size={13} /> Connect Acyn Wallet
          </div>
          <p className="field-label" style={{ marginBottom: 10 }}>
            Create a business account at Acyn Wallet, complete verification, and generate a partner API key
            from its admin console -- paste it here. See INTEGRATIONS.md#acyn-wallet.
          </p>
          <div style={{ display: "flex", gap: 8 }}>
            <Input
              placeholder="pk_live_..."
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              style={{ flex: 1 }}
            />
            <Button onClick={connect} disabled={connecting}>
              {connecting ? "Connecting..." : "Connect"}
            </Button>
          </div>
          <p className="field-label" style={{ marginTop: 10 }}>
            Don't have a business account yet?{" "}
            <a href="https://b2bwallet.acyninnovation.com" target="_blank" rel="noopener">
              Create one at Acyn Wallet <Icon name="arrow-up-right" size={11} />
            </a>
          </p>
        </Card>
      ) : null}

      {connected ? (
        <>
          {receiveAddress ? (
            <Card style={{ marginBottom: 16 }}>
              <div className="field-label" style={{ marginBottom: 8 }}>
                <Icon name="arrow-up-right" size={13} /> Receive
              </div>
              <p className="field-label" style={{ marginBottom: 8 }}>
                Share this address to get paid -- Acyn Wallet's deposit watcher credits it automatically, no action
                needed here.
              </p>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Input value={receiveAddress} readOnly style={{ flex: 1, fontFamily: "monospace" }} />
                <Button size="sm" variant="secondary" onClick={() => copyAddress(receiveAddress)}>
                  {copied ? "Copied!" : "Copy"}
                </Button>
              </div>
            </Card>
          ) : null}

          <Card style={{ marginBottom: 16 }}>
            <div className="page-header" style={{ marginBottom: 10 }}>
              <div className="field-label">
                <Icon name="wallet" size={13} /> Balances
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <a href="https://b2bwallet.acyninnovation.com" target="_blank" rel="noopener">
                  <Button size="sm" variant="ghost">
                    Open Acyn Wallet <Icon name="arrow-up-right" size={11} />
                  </Button>
                </a>
                <Button size="sm" variant="secondary" onClick={doRefreshWallets} disabled={refreshing}>
                  {refreshing ? "Refreshing..." : "Refresh"}
                </Button>
              </div>
            </div>
            {wallets.length === 0 ? (
              <div className="empty-state">No cached balances yet -- hit Refresh to pull from Acyn Wallet.</div>
            ) : (
              wallets.map((w) => (
                <div key={w.id} className="pos-totals-row">
                  <span>
                    {w.network} · {w.currency}
                  </span>
                  <span>{w.balance}</span>
                </div>
              ))
            )}
          </Card>

          <Card style={{ marginBottom: 16 }}>
            <div className="field-label" style={{ marginBottom: 10 }}>
              Request payout
            </div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              <FieldWrap label="To address">
                <Input value={toAddress} onChange={(e) => setToAddress(e.target.value)} style={{ width: 220 }} />
              </FieldWrap>
              <FieldWrap label="Amount">
                <Input value={amount} onChange={(e) => setAmount(e.target.value)} style={{ width: 100 }} />
              </FieldWrap>
              <FieldWrap label="Currency">
                <Input value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} style={{ width: 80 }} />
              </FieldWrap>
              <FieldWrap label="Network">
                <Input value={network} onChange={(e) => setNetwork(e.target.value)} style={{ width: 140 }} placeholder="base-sepolia" />
              </FieldWrap>
              <FieldWrap label="Reason">
                <Input value={reason} onChange={(e) => setReason(e.target.value)} style={{ width: 160 }} />
              </FieldWrap>
            </div>
            <Button style={{ marginTop: 10 }} onClick={submitPayout} disabled={submittingPayout}>
              {submittingPayout ? "Requesting..." : "Request payout"}
            </Button>
            <p className="field-label" style={{ marginTop: 8 }}>
              Never broadcasts directly -- queues into Acyn Wallet's own dual-control admin approval queue.
            </p>
          </Card>

          <Card>
            <div className="field-label" style={{ marginBottom: 10 }}>
              Recent transactions
            </div>
            {transactions.length === 0 ? (
              <div className="empty-state">No payouts or credit transfers yet.</div>
            ) : (
              transactions.slice(0, 10).map((t) => (
                <div key={t.id} className="pos-totals-row">
                  <span>
                    {t.kind === "payout" ? "Payout" : "Credit transfer"} · {t.amount} {t.currency}
                  </span>
                  <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <Badge tone={statusTone(t.status)}>{t.status}</Badge>
                    <Button size="sm" variant="ghost" onClick={() => pollStatus(t.id)}>
                      <Icon name="history" size={13} />
                    </Button>
                  </span>
                </div>
              ))
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
