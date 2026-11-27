import { useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { approveAtTill, listPosCashiers, posDeviceToken, type PosCashier } from "../../lib/posPin";

const APPROVERS = new Set(["owner", "admin", "branch_manager", "team_leader"]);

/** A team leader or manager says yes to a price cut or big discount with
 * their PIN on this till (checked by the kernel). Their name goes on the
 * sale. */
export function OverrideApproval({ reasons, onClose, onApproved }: { reasons: string[]; onClose: () => void; onApproved: (by: string) => void }) {
  const [people, setPeople] = useState<PosCashier[] | null>(null);
  const [who, setWho] = useState("");
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const trusted = Boolean(posDeviceToken());

  useEffect(() => {
    if (!trusted) return;
    listPosCashiers()
      .then((all) => setPeople(all.filter((p) => p.has_pin && (!p.role || APPROVERS.has(p.role)))))
      .catch(() => setPeople([]));
  }, [trusted]);

  async function approve() {
    if (!who) return setError("Choose who approves");
    if (pin.length < 4) return setError("Type their PIN");
    setBusy(true);
    setError(null);
    try {
      await approveAtTill(who, pin);
      const p = people?.find((x) => x.user_id === who);
      onApproved(p?.email || p?.name || who);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not approve");
      setPin("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="till-sheet-backdrop" onClick={onClose}>
      <div className="till-panel glass till-sheet" role="dialog" aria-label="A manager's OK" onClick={(e) => e.stopPropagation()} style={{ display: "grid", gap: 10 }}>
        <h2 style={{ margin: 0, fontSize: 22 }}>A manager's OK</h2>
        <ul className="till-text" style={{ margin: 0, paddingLeft: 18 }}>
          {reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
        {!trusted ? (
          <p className="till-text" style={{ margin: 0 }}>
            A team leader or manager approves with their PIN on a trusted till, or signs in here and takes the sale. Or put the price back.
          </p>
        ) : (
          <>
            <select className="till-input" aria-label="Who approves" value={who} onChange={(e) => setWho(e.target.value)}>
              <option value="">Team leader or manager…</option>
              {(people ?? []).map((p) => (
                <option key={p.user_id} value={p.user_id}>
                  {p.name}
                </option>
              ))}
            </select>
            <input
              className="till-input"
              type="password"
              inputMode="numeric"
              autoComplete="off"
              aria-label="Their PIN"
              placeholder="Their PIN"
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && void approve()}
            />
          </>
        )}
        {error ? (
          <div className="till-error" role="alert" style={{ margin: 0 }}>
            {error}
          </div>
        ) : null}
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="till-btn" onClick={onClose}>
            Back to the order
          </button>
          {trusted ? (
            <button type="button" className="till-btn primary" onClick={() => void approve()} disabled={busy}>
              {busy ? "Checking…" : "Approve"}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
