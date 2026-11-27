import { useState } from "react";
import { api, ApiError } from "../../lib/api";
import { formatMoney, useOrgSettings } from "../../lib/orgSettings";

type Stretch = { counted_cents: number; expected_cents: number; short_cents: number };

/** Switch cashier mid-shift (plan 20.3): the outgoing cashier counts the
 * drawer first, blind (the expected amount shows only after), so a
 * shortage stays with the stretch it happened in. Then the next cashier
 * signs in. An older Invoicing without handovers just switches. */
export function Handover({ shiftId, onClose, onDone }: { shiftId: string; onClose: () => void; onDone: () => void }) {
  const { currency } = useOrgSettings();
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Stretch | null>(null);

  async function save() {
    const value = Number.parseFloat(amount);
    if (!Number.isFinite(value) || value < 0) return setError("Count the cash in the drawer and type the total");
    setBusy(true);
    setError(null);
    try {
      setResult(await api.post<Stretch>(`/api/invoicing/pos/shifts/${shiftId}/handover`, { counted_cents: Math.round(value * 100) }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) return onDone(); // Invoicing not updated yet
      setError(err instanceof ApiError ? err.message : "Could not record the count");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="till-sheet-backdrop" onClick={result ? undefined : onClose}>
      <div className="till-panel glass till-sheet" role="dialog" aria-label="Hand over the till" onClick={(e) => e.stopPropagation()} style={{ display: "grid", gap: 10 }}>
        <h2 style={{ margin: 0, fontSize: 22 }}>Hand over the till</h2>
        {result ? (
          <>
            <p style={{ margin: 0, fontSize: 17 }} role="status">
              {result.short_cents === 0
                ? "The drawer is right."
                : result.short_cents < 0
                  ? `${formatMoney(-result.short_cents)} short.`
                  : `${formatMoney(result.short_cents)} over.`}
            </p>
            <p className="till-text" style={{ margin: 0 }}>
              Counted {formatMoney(result.counted_cents)}, expected {formatMoney(result.expected_cents)}. It's on the shift report under your name.
            </p>
            <button type="button" className="till-btn primary" onClick={onDone} autoFocus>
              Next cashier
            </button>
          </>
        ) : (
          <>
            <p className="till-text" style={{ margin: 0 }}>
              Count the cash in the drawer before the next cashier takes over.
            </p>
            <input
              className="till-input"
              aria-label={`Cash in the drawer (${currency})`}
              placeholder={`Cash in the drawer (${currency})`}
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void save()}
              autoFocus
            />
            {error ? (
              <div className="till-error" role="alert" style={{ margin: 0 }}>
                {error}
              </div>
            ) : null}
            <div style={{ display: "flex", gap: 8 }}>
              <button type="button" className="till-btn" onClick={onClose}>
                Cancel
              </button>
              <button type="button" className="till-btn primary" onClick={() => void save()} disabled={busy}>
                {busy ? "Saving…" : "Save count"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
