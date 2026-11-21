import { useEffect, useState } from "react";
import { formatMoney } from "../../lib/orgSettings";
import { maskKePhone } from "./phone";

export type OnlineStatus = "starting" | "pending" | "paid" | "void";

/** A sale waiting on a gateway that confirms it by itself (M-Pesa prompt,
 * Paystack page, Pesapal). Follows the usual push-payment checkout: one
 * screen, the amount large, where the customer is in the steps, how long
 * it has been, and the ways out (resend, cancel, another method). The
 * order screen stays blocked so the same cart can't be sold twice.
 * Paid hands over to the till's ordinary "Paid" screen and receipt. */
export function OnlinePayment({
  provider,
  status,
  amountCents,
  phoneDigits,
  returnedCents,
  error,
  onResend,
  onCancel,
  onOtherMethod,
  onReopenPage,
  onDone,
}: {
  provider: "Paystack" | "Pesapal";
  status: OnlineStatus;
  amountCents: number;
  /** Set for an M-Pesa prompt sent to this number. */
  phoneDigits?: string;
  /** Cash etc. to hand back after a split sale was cancelled. */
  returnedCents?: number;
  error?: string | null;
  onResend?: () => void;
  /** Absent for Pesapal, which can't be cancelled from here. */
  onCancel?: () => void;
  onOtherMethod?: () => void;
  onReopenPage?: () => void;
  onDone: () => void;
}) {
  const [startedAt] = useState(() => Date.now());
  const [now, setNow] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (status !== "pending" && status !== "starting") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [status]);
  useEffect(() => setBusy(false), [status]);

  const secs = Math.max(0, Math.floor((now - startedAt) / 1000));
  const elapsed = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  const prompt = !!phoneDigits;
  // An M-Pesa prompt expires on the phone after about a minute.
  const slow = status === "pending" && secs >= (prompt ? 60 : 120);
  const canResend = prompt && status === "pending" && secs >= 30;

  const title = prompt ? "M-Pesa" : provider === "Paystack" ? "Card or bank (Paystack)" : "Pesapal";
  const steps = prompt
    ? ["Prompt sent", "Customer enters their M-Pesa PIN", "Payment confirmed"]
    : ["Payment page opened", "Customer pays on the page", "Payment confirmed"];
  // A cancelled or failed payment stops at the customer's step, not done.
  const at = status === "starting" ? 0 : status === "paid" ? 2 : 1;

  let message: string;
  if (status === "starting") message = prompt ? "Sending the prompt to the customer's phone…" : "Opening the payment page…";
  else if (status === "void")
    message = returnedCents
      ? `Sale cancelled. Hand back ${formatMoney(returnedCents)}.`
      : "The payment didn't go through or was cancelled. Nothing was charged.";
  else if (slow)
    message = prompt
      ? "No answer yet. The prompt may have expired on their phone: resend it, or take another method."
      : "Still waiting. Ask the customer if the page shows an error, or take another method.";
  else
    message = prompt
      ? `Ask the customer to check ${maskKePhone(phoneDigits!)} and enter their M-Pesa PIN.`
      : "The customer pays on the Paystack page. This screen updates by itself.";

  const act = (fn?: () => void) => () => {
    if (!fn) return;
    setBusy(true);
    fn();
  };

  return (
    <div className="till-stage">
      <div />
      <div className="till-stage-center">
        <section className="till-panel glass" aria-labelledby="online-title" style={{ textAlign: "center" }}>
          <h2 id="online-title">{title}</h2>
          <div className="till-change" style={{ fontSize: 44 }}>
            {formatMoney(amountCents)}
          </div>
          {prompt ? <div className="till-text">{maskKePhone(phoneDigits!)}</div> : null}

          <ol className="till-steps" aria-label="Payment progress">
            {steps.map((s, i) => (
              <li
                key={s}
                className={i < at || (status === "paid" && i === at) ? "done" : i === at && status !== "void" ? "now" : ""}
                aria-current={i === at && status !== "void" ? "step" : undefined}
              >
                <span className="till-step-dot" aria-hidden="true">
                  {i < at || status === "paid" ? "✓" : i + 1}
                </span>
                {s}
              </li>
            ))}
          </ol>

          <p
            role="status"
            aria-live="polite"
            className={`till-chip ${status === "void" || slow ? "warn" : "ok"}`}
            style={{ whiteSpace: "normal", margin: 0, lineHeight: 1.4 }}
          >
            {message}
          </p>
          {status === "pending" || status === "starting" ? (
            <div className="till-text" aria-label={`Waiting for ${elapsed}`}>
              {status === "pending" ? <span className="till-spinner" aria-hidden="true" /> : null} {elapsed}
            </div>
          ) : null}
          {error ? (
            <div className="till-error" role="alert" style={{ margin: 0 }}>
              {error}
            </div>
          ) : null}

          <div className="till-panel-actions" style={{ flexWrap: "wrap" }}>
            {status === "pending" && onCancel ? (
              <button type="button" className="till-btn" disabled={busy} onClick={act(onCancel)}>
                Cancel sale
              </button>
            ) : null}
            {status === "pending" && !prompt && onReopenPage ? (
              <button type="button" className="till-btn" onClick={onReopenPage}>
                Open the page again
              </button>
            ) : null}
            {prompt && status === "pending" ? (
              <button
                type="button"
                className="till-btn"
                disabled={!canResend || busy}
                title={canResend ? "" : "Wait 30 seconds before sending another prompt"}
                onClick={act(onResend)}
              >
                {canResend ? "Resend prompt" : `Resend in ${30 - secs}s`}
              </button>
            ) : null}
            {status === "pending" && provider === "Pesapal" ? (
              <button type="button" className="till-btn" onClick={onDone}>
                Stop waiting
              </button>
            ) : null}
            {status === "void" ? (
              <>
                {onOtherMethod ? (
                  <button type="button" className="till-btn" onClick={onOtherMethod}>
                    Another method
                  </button>
                ) : null}
                {prompt && onResend ? (
                  <button type="button" className="till-btn primary" autoFocus onClick={act(onResend)}>
                    Try M-Pesa again
                  </button>
                ) : (
                  <button type="button" className="till-btn primary" autoFocus onClick={onDone}>
                    Back to the order
                  </button>
                )}
              </>
            ) : null}
          </div>
        </section>
      </div>
      <div />
    </div>
  );
}
