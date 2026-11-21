import { useMemo, useState } from "react";
import { formatMoney } from "../../lib/orgSettings";
import { PosNumpad } from "./PosNumpad";
import { methodLabel } from "./receipt";

/** A gateway that confirms the payment itself (Paystack, Pesapal). */
export interface OnlineMethod {
  key: string;
  label: string;
  hint: string;
  start: () => void;
}

export interface Tender {
  method: string;
  cents: number;
}

/** Notes worth offering as one-tap "customer gave" amounts. */
const NOTES = [5000, 10000, 20000, 50000, 100000];

function quickAmounts(due: number): number[] {
  const out = new Set<number>([due]);
  for (const n of NOTES) {
    const up = Math.ceil(due / n) * n;
    if (up > due) out.add(up);
  }
  return [...out].sort((a, b) => a - b).slice(0, 4);
}

/** Taking payment. Pick a method and its line takes what's still due;
 * the keypad changes the selected line (what the customer handed over).
 * Typing on the keyboard does the same: "1500" keys in 1,500, Enter
 * validates, Escape goes back to the order.
 * Several methods split the bill. Only cash can be over the amount due:
 * the difference is change. */
export function PosPayment({
  totalCents,
  taxLabel,
  taxCents,
  manual = ["cash", "mpesa", "card"],
  online = [],
  onCancel,
  onPaid,
  buyer,
}: {
  totalCents: number;
  taxLabel: string;
  taxCents: number;
  /** Methods the cashier confirms by hand, as this till offers them. */
  manual?: string[];
  online?: OnlineMethod[];
  onCancel: () => void;
  onPaid: (tenders: Tender[], changeCents: number) => void;
  /** The buyer's KRA PIN, for a business buying (BuyerPin). */
  buyer?: React.ReactNode;
}) {
  const [lines, setLines] = useState<Tender[]>(manual.length ? [{ method: manual[0], cents: totalCents }] : []);
  const [selected, setSelected] = useState(0);
  const [entry, setEntry] = useState<string | null>(null);

  const paid = lines.reduce((s, l) => s + l.cents, 0);
  const remaining = Math.max(0, totalCents - paid);
  const cashIn = lines.filter((l) => l.method === "cash").reduce((s, l) => s + l.cents, 0);
  const over = Math.max(0, paid - totalCents);
  const change = Math.min(over, cashIn);
  const valid = paid >= totalCents && over <= cashIn;

  function setSelectedCents(cents: number) {
    setLines((ls) => ls.map((l, i) => (i === selected ? { ...l, cents } : l)));
  }

  function key(k: string) {
    const next = (() => {
      const e = entry ?? "";
      if (k === "." && e.includes(".")) return e;
      if (e.includes(".") && e.split(".")[1].length >= 2) return e;
      if (e.length >= 10) return e;
      return e + k;
    })();
    setEntry(next);
    setSelectedCents(Math.round((Number.parseFloat(next || "0") || 0) * 100));
  }

  function back() {
    const next = (entry ?? "").slice(0, -1);
    setEntry(next);
    setSelectedCents(Math.round((Number.parseFloat(next || "0") || 0) * 100));
  }

  function addMethod(method: string) {
    // Swap the only, untouched line's method; otherwise add a line for
    // what's still due.
    if (lines.length === 1 && entry === null) {
      setLines([{ method, cents: totalCents }]);
      setSelected(0);
      return;
    }
    const existing = lines.findIndex((l) => l.method === method);
    if (existing >= 0) {
      setSelected(existing);
      setEntry(null);
      return;
    }
    setLines((ls) => [...ls, { method, cents: remaining }]);
    setSelected(lines.length);
    setEntry(null);
  }

  function removeLine(i: number) {
    setLines((ls) => (ls.length === 1 ? ls : ls.filter((_, j) => j !== i)));
    setSelected(0);
    setEntry(null);
  }

  // What this line still has to cover, whatever was typed into it.
  const lineDue = Math.max(0, totalCents - (paid - (lines[selected]?.cents ?? 0)));
  const quick = useMemo(() => quickAmounts(lineDue), [lineDue]);

  function validate() {
    // Record what stays in the drawer: cash handed over minus change.
    let changeLeft = change;
    const tenders = lines
      .map((l) => {
        if (l.method !== "cash" || changeLeft === 0) return l;
        const take = Math.min(changeLeft, l.cents);
        changeLeft -= take;
        return { ...l, cents: l.cents - take };
      })
      .filter((l) => l.cents > 0);
    onPaid(tenders, change);
  }

  return (
    <div className="till-stage">
      <div className="till-stage-head">
        <button type="button" className="till-chip glass" style={{ justifySelf: "start", cursor: "pointer" }} onClick={onCancel}>
          ← Back to order
        </button>
        <div className="till-stage-title">Payment</div>
        <div />
      </div>
      <div className="till-paygrid" style={{ marginTop: 24 }}>
        <div style={{ display: "grid", gap: 16 }}>
          <div className="glass" style={{ borderRadius: 24, padding: 24 }}>
            <div className="till-text">Amount due</div>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 52, fontWeight: 800, fontVariantNumeric: "tabular-nums" }}>
              {formatMoney(totalCents)}
            </div>
            <div className="till-text">
              {taxLabel}: {formatMoney(taxCents)}
            </div>
          </div>
          {buyer}
          <div className="till-methods">
            {manual.map((m) => (
              <button
                key={m}
                type="button"
                className={`till-method glass${lines[selected]?.method === m ? " active" : ""}`}
                onClick={() => addMethod(m)}
              >
                {methodLabel(m)}
              </button>
            ))}
            {online.map((o) => (
              <button key={o.key} type="button" className="till-method glass" onClick={o.start} style={{ lineHeight: 1.2 }}>
                {o.label}
                <span style={{ display: "block", fontSize: 13, fontWeight: 500, color: "var(--text-muted)" }}>
                  {o.hint}
                </span>
              </button>
            ))}
          </div>
          <div className="glass" style={{ borderRadius: 20, padding: 12 }}>
            {lines.map((l, i) => (
              <div
                key={i}
                className={`till-line${i === selected ? " selected" : ""}`}
                style={{ borderRadius: 12 }}
                onClick={() => (setSelected(i), setEntry(null))}
              >
                <span className="till-line-name">{methodLabel(l.method)}</span>
                <span className="till-line-amount">
                  {formatMoney(l.cents)}
                  {lines.length > 1 ? (
                    <button
                      type="button"
                      aria-label="Remove"
                      onClick={(e) => (e.stopPropagation(), removeLine(i))}
                      style={{ marginLeft: 10, border: 0, background: "none", cursor: "pointer", fontSize: 18 }}
                    >
                      ×
                    </button>
                  ) : null}
                </span>
              </div>
            ))}
          </div>
          {lines[selected]?.method === "card" ? (
            <p className="till-text">
              Take the card or tap on the PDQ (Pesapal or your bank's). Validate once it prints approved; it works offline too.
            </p>
          ) : null}
          {lines[selected]?.method === "mpesa" ? (
            <p className="till-text">
              Paid to your till or paybill number: check the M-Pesa message for this amount before you validate. Through
              Paystack or Pesapal the payment confirms itself.
            </p>
          ) : null}
        </div>
        <div className="glass" style={{ borderRadius: 24, padding: 20, display: "grid", gap: 12 }}>
          {remaining > 0 ? (
            <div className="till-row strong">
              <span>Still due</span>
              <span className="short">{formatMoney(remaining)}</span>
            </div>
          ) : (
            <div style={{ textAlign: "center" }}>
              <div className="till-text">Change</div>
              <div className="till-change">{formatMoney(change)}</div>
            </div>
          )}
          {lines[selected]?.method === "cash" ? (
            <div className="till-quick">
              {quick.map((q) => (
                <button key={q} type="button" className="glass" onClick={() => (setSelectedCents(q), setEntry(null))}>
                  {formatMoney(q, { whole: q % 100 === 0 })}
                </button>
              ))}
            </div>
          ) : null}
          <PosNumpad
            onKey={key}
            onBackspace={back}
            keyboard={{ onEnter: () => valid && validate(), onEscape: onCancel }}
          />
          {over > cashIn ? <div className="till-error" style={{ margin: 0 }}>Only cash can be more than the amount due.</div> : null}
          <button type="button" className="till-pay" style={{ margin: 0 }} disabled={!valid} onClick={validate}>
            <span>Validate</span>
            <span>{formatMoney(paid)}</span>
          </button>
        </div>
      </div>
      <div />
    </div>
  );
}
