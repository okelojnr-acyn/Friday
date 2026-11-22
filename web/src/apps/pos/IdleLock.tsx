import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../lib/api";
import { resumeTill } from "../../lib/posPin";

/** The idle till (plan 20.3): after IDLE_MS without a touch or key the
 * till locks over the open order. The cashier who clocked in continues
 * with their own PIN; anyone else clocks this cashier out and signs in
 * as themselves, so one cashier never sells on another's session. Keys
 * are caught here first, so a barcode scanner can't ring up an item on
 * the locked till. */
export const IDLE_MS = 5 * 60_000;

export function IdleLock({ email, onResume, onClockOut }: { email: string; onResume: () => void; onClockOut: () => void }) {
  const [pin, setPin] = useState("");
  const pinRef = useRef("");
  const busyRef = useRef(false);
  const put = (p: string) => {
    pinRef.current = p;
    setPin(p);
  };
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(full: string) {
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      await resumeTill(full);
      onResume();
    } catch (err) {
      put("");
      const left = err instanceof ApiError ? (err.data as { tries_left?: number }).tries_left : undefined;
      setError(
        left !== undefined
          ? `Wrong PIN. ${left} ${left === 1 ? "try" : "tries"} left.`
          : err instanceof ApiError
            ? err.message
            : "Couldn't check the PIN",
      );
      // Locked out: the passkey is needed again.
      if (err instanceof ApiError && err.status === 423) onClockOut();
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }

  function press(k: string) {
    if (busyRef.current) return;
    const p = pinRef.current;
    if (k === "back") return put(p.slice(0, -1));
    if (p.length >= 6) return;
    put(p + k);
    if (p.length + 1 === 6) void submit(p + k);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      e.stopImmediatePropagation();
      e.preventDefault();
      if (/^[0-9]$/.test(e.key)) press(e.key);
      else if (e.key === "Backspace") press("back");
    }
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="till-lock" role="dialog" aria-modal="true" aria-label="Till locked">
      <div className="till-lock-card">
        <h1 className="page-title">Till locked</h1>
        <p className="till-text" style={{ margin: 0 }}>
          {email} is clocked in. Enter your PIN to carry on.
        </p>
        <div className="till-lock-dots" aria-label={`${pin.length} of 6 digits`}>
          {Array.from({ length: 6 }, (_, i) => (
            <span key={i} className={i < pin.length ? "on" : ""} />
          ))}
        </div>
        {error ? (
          <div className="error-banner" role="alert">
            {error}
          </div>
        ) : null}
        <div className="till-lock-pad">
          {["1", "2", "3", "4", "5", "6", "7", "8", "9", "", "0", "back"].map((k, i) =>
            k ? (
              <button key={i} type="button" disabled={busy} onClick={() => press(k)} aria-label={k === "back" ? "Delete" : k}>
                {k === "back" ? "⌫" : k}
              </button>
            ) : (
              <span key={i} />
            ),
          )}
        </div>
        <button type="button" className="btn btn-secondary" onClick={onClockOut}>
          Not you? Clock out and switch cashier
        </button>
        <p className="field-label" style={{ margin: 0 }}>
          No PIN yet? Clock out and scan your fingerprint; then set one in the till menu.
        </p>
      </div>
    </div>
  );
}
