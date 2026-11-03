import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../lib/api";
import { fetchMyWallet, setMyWallet } from "../lib/minions";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import { Icon } from "../ui/Icon";

/** The employee's own receiving address, pasted from their personal
 * Acyn Wallet consumer app -- there's no partner-side lookup-by-email on
 * Acyn's Partner API (see apps/minions/app/main.py's set_my_wallet), so
 * this is the only way payroll/expense payouts know where to send
 * money. */
export function WalletPage() {
  const [address, setAddress] = useState("");
  const [network, setNetwork] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMyWallet()
      .then((w) => {
        setAddress(w.wallet_address);
        setNetwork(w.wallet_network);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load your wallet link"))
      .finally(() => setLoaded(true));
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await setMyWallet({ wallet_address: address.trim(), wallet_network: network.trim() });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save your wallet link");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Wallet</h1>
      </div>

      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      {!loaded ? (
        <div className="page spinner">Loading...</div>
      ) : (
        <Card>
          <div className="field-label" style={{ marginBottom: 10 }}>
            <Icon name="key" size={13} /> Receiving address
          </div>
          <p className="field-label" style={{ marginBottom: 10 }}>
            Open your personal Acyn Wallet app, copy your address, and paste it here -- this is where payroll and
            approved expense reimbursements get sent.
          </p>
          <form onSubmit={onSubmit} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
            <FieldWrap label="Wallet address" required>
              <Input value={address} onChange={(e) => setAddress(e.target.value)} style={{ width: 280, fontFamily: "monospace" }} />
            </FieldWrap>
            <FieldWrap label="Network" required>
              <Input value={network} onChange={(e) => setNetwork(e.target.value)} placeholder="base-sepolia" style={{ width: 160 }} />
            </FieldWrap>
            <Button type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </Button>
          </form>
          {saved ? <p className="field-label" style={{ marginTop: 8, color: "var(--success, green)" }}>Saved.</p> : null}
        </Card>
      )}
    </div>
  );
}
