import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { formatMoney, useOrgSettings } from "../../lib/orgSettings";
import { CATEGORIES } from "../../lib/minions";

/** Whether this business lets cashiers pay out of the till (Business
 * settings > Spending; off by default), and the most for one payout. */
export function useTillPayouts(): { allowed: boolean; most: number } {
  const [rule, setRule] = useState({ allowed: false, most: 0 });
  useEffect(() => {
    api
      .get<{ till_payouts: boolean; petty_slip_max: number }>("/orgs/spending-policy")
      .then((p) => setRule({ allowed: p.till_payouts, most: p.petty_slip_max }))
      .catch(() => {}); // an older kernel: off
  }, []);
  return rule;
}

/** Till menu > Pay out: cash out of the drawer for a small business spend.
 * It's on the shift (less cash expected at close) and in the books. */
export function PayOut({ shiftId, most, onClose, onDone }: { shiftId: string; most: number; onClose: () => void; onDone: (text: string) => void }) {
  const { currency } = useOrgSettings();
  const [amount, setAmount] = useState("");
  const [what, setWhat] = useState("");
  const [category, setCategory] = useState("supplies");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cents = Math.round((Number.parseFloat(amount || "0") || 0) * 100);

  async function save() {
    if (cents <= 0 || !what.trim()) return setError("Enter the amount and what it was for");
    if (most && cents > most) return setError(`The till pays out at most ${formatMoney(most)} at a time`);
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/invoicing/pos/shifts/${shiftId}/paid_outs`, { amount_cents: cents, description: what.trim(), category });
      onDone(`Paid out ${formatMoney(cents)}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not record the payout");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="till-sheet-backdrop" onClick={onClose}>
      <div
        className="till-panel glass till-sheet"
        role="dialog"
        aria-label="Pay out of the till"
        onClick={(e) => e.stopPropagation()}
        style={{ display: "grid", gap: 10 }}
      >
        <h2 style={{ margin: 0, fontSize: 22 }}>Pay out of the till</h2>
        <input
          className="till-input"
          aria-label={`Amount (${currency})`}
          placeholder={`Amount (${currency})`}
          inputMode="decimal"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          autoFocus
        />
        <input
          className="till-input"
          aria-label="What it was for"
          placeholder="What it was for, e.g. Water delivery"
          maxLength={200}
          value={what}
          onChange={(e) => setWhat(e.target.value)}
        />
        <select className="till-input" aria-label="Kind of cost" value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </select>
        {error ? (
          <div className="till-error" role="alert" style={{ margin: 0 }}>
            {error}
          </div>
        ) : null}
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="till-btn primary" disabled={busy} onClick={save}>
            {busy ? "Saving…" : "Pay out"}
          </button>
          <button type="button" className="till-btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
