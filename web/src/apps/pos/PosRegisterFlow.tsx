import { useEffect, useState } from "react";
import { ApiError } from "../../lib/api";
import { formatMoney, useOrgSettings } from "../../lib/orgSettings";
import {
  closeShift,
  createRegister,
  keypadToCents,
  openShift,
  type PosRegister,
  type PosShift,
} from "../../lib/posApi";
import { Icon } from "../../ui/Icon";
import { PosNumpad } from "./PosNumpad";
import { methodLabel } from "./receipt";

function useClock(): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function Clock() {
  const now = useClock();
  return (
    <div className="till-clock">
      <span className="till-clock-time">
        {now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
      </span>
      <span className="till-clock-date">
        {now.toLocaleDateString(undefined, { weekday: "long" })}
        <br />
        {now.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}
      </span>
    </div>
  );
}

/** Keypad entry of an amount, e.g. the float or the counted cash. */
function useAmountEntry() {
  const [entry, setEntry] = useState("");
  return {
    entry,
    cents: keypadToCents(entry),
    key: (k: string) =>
      setEntry((e) => {
        if (k === "." && e.includes(".")) return e;
        if (e.includes(".") && e.split(".")[1].length >= 2) return e;
        if (e.length >= 10) return e;
        return e === "0" && k !== "." ? k : e + k;
      }),
    back: () => setEntry((e) => e.slice(0, -1)),
    set: setEntry,
  };
}

function Stage({ title, sub, children, foot }: { title: string; sub?: string; children: React.ReactNode; foot?: React.ReactNode }) {
  const { name } = useOrgSettings();
  return (
    <div className="till-stage">
      <div className="till-stage-head">
        <Clock />
        <div>
          <div className="till-stage-title">{title}</div>
          {sub ? <div className="till-stage-sub">{sub}</div> : null}
        </div>
        <div style={{ textAlign: "right", fontFamily: "var(--font-display)", fontSize: 22, fontWeight: 700 }}>
          {name}
        </div>
      </div>
      <div className="till-stage-center">{children}</div>
      <div style={{ display: "flex", justifyContent: "center", gap: 12 }}>{foot}</div>
    </div>
  );
}

/** Which till is this device? Asked once; remembered on the device. */
export function ChooseRegister({
  registers,
  canManage,
  onChosen,
}: {
  registers: PosRegister[];
  canManage: boolean;
  onChosen: (r: PosRegister) => void;
}) {
  const [name, setName] = useState("");
  const [store, setStore] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const active = registers.filter((r) => r.active);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      onChosen(await createRegister(name.trim(), store.trim()));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not add the till.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stage title="Which till is this?" sub="Asked once on this device.">
      <div className="till-panel glass">
        {active.map((r) => (
          <button key={r.id} type="button" className="till-btn" style={{ textAlign: "left", padding: "0 18px" }} onClick={() => onChosen(r)}>
            {r.name}
            {r.location_name ? <span style={{ color: "var(--text-muted)", fontWeight: 500 }}> · {r.location_name}</span> : null}
            {r.open_shift ? <span style={{ float: "right", color: "#1f6e44" }}>open</span> : null}
          </button>
        ))}
        {canManage ? (
          <>
            <h2 style={{ fontSize: 18, marginTop: 8 }}>Add a till</h2>
            <input className="till-input" placeholder="Till name, e.g. Till 2" value={name} onChange={(e) => setName(e.target.value)} />
            <input className="till-input" placeholder="Store, e.g. Westlands" value={store} onChange={(e) => setStore(e.target.value)} />
            {error ? <div className="till-error" style={{ margin: 0 }}>{error}</div> : null}
            <button type="button" className="till-btn primary" disabled={!name.trim() || busy} onClick={add}>
              Add and use this till
            </button>
          </>
        ) : active.length === 0 ? (
          <p className="till-text">No tills yet. Ask an owner or admin to sign in here and add one.</p>
        ) : null}
      </div>
    </Stage>
  );
}

/** The idle screen and opening the register with the counted float. */
export function OpenRegister({
  register,
  onOpened,
  onSwitchTill,
  onClockOut,
  onSwitchCashier,
  onPinSettings,
  overlay,
}: {
  register: PosRegister | null;
  onOpened: (s: PosShift) => void;
  onSwitchTill: () => void;
  onClockOut: () => void;
  onSwitchCashier: () => void;
  onPinSettings: () => void;
  overlay?: React.ReactNode;
}) {
  const [counting, setCounting] = useState(false);
  const amount = useAmountEntry();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const title = register?.name ?? "Main till";

  async function open() {
    setBusy(true);
    setError(null);
    try {
      onOpened(await openShift(register?.id ?? null, amount.cents));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not open the register.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stage
      title={title}
      sub={register?.location_name || undefined}
      foot={
        <>
          <button type="button" className="till-chip glass" style={{ cursor: "pointer" }} onClick={onSwitchTill}>
            Not this till?
          </button>
          <button type="button" className="till-chip glass" style={{ cursor: "pointer" }} onClick={onSwitchCashier}>
            Switch cashier
          </button>
          <button type="button" className="till-chip glass" style={{ cursor: "pointer" }} onClick={onPinSettings}>
            Cashier PIN
          </button>
          <button type="button" className="till-chip glass" style={{ cursor: "pointer" }} onClick={onClockOut}>
            Clock out
          </button>
          {overlay}
        </>
      }
    >
      {!counting ? (
        <button type="button" className="till-big-tile glass" onClick={() => setCounting(true)}>
          <Icon name="storefront" size={44} />
          Open register
        </button>
      ) : (
        <div className="till-panel glass">
          <h2>Cash in the drawer</h2>
          <p className="till-text">Count the float you're starting with. Enter 0 if the drawer is empty.</p>
          <div className="till-amount">{formatMoney(amount.cents)}</div>
          <PosNumpad onKey={amount.key} onBackspace={amount.back} />
          {error ? <div className="till-error" style={{ margin: 0 }}>{error}</div> : null}
          <div className="till-panel-actions">
            <button type="button" className="till-btn" onClick={() => setCounting(false)}>
              Back
            </button>
            <button type="button" className="till-btn primary" disabled={busy} onClick={open}>
              {busy ? "Opening…" : "Open register"}
            </button>
          </div>
        </div>
      )}
    </Stage>
  );
}

/** Closing: count the drawer first (the expected amount is not shown,
 * so the count is honest), then see the result. */
export function CloseRegister({
  register,
  shift,
  pendingSales,
  onCancel,
  onClosed,
}: {
  register: PosRegister | null;
  shift: PosShift;
  pendingSales: number;
  onCancel: () => void;
  onClosed: () => void;
}) {
  const amount = useAmountEntry();
  const [note, setNote] = useState("");
  const [closed, setClosed] = useState<PosShift | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      setClosed(await closeShift(shift.id, amount.cents, note));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not close the register.");
    } finally {
      setBusy(false);
    }
  }

  if (closed) {
    const expected = closed.expected_cents ?? 0;
    const counted = closed.closing_count_cents ?? 0;
    const diff = counted - expected;
    const methods = Object.entries(closed.summary?.by_method ?? {});
    return (
      <Stage title={`${register?.name ?? "Register"} closed`} sub={new Date(closed.closed_at ?? Date.now()).toLocaleString()}>
        <div className="till-panel glass">
          <div className="till-row">
            <span>Sales</span>
            <span>{closed.summary?.sales ?? 0}</span>
          </div>
          {closed.summary?.returns ? (
            <div className="till-row">
              <span>Returns</span>
              <span>{closed.summary.returns}</span>
            </div>
          ) : null}
          {methods.map(([m, v]) => (
            <div className="till-row" key={m}>
              <span>{m === "refund" ? "Refunds paid out" : methodLabel(m)}</span>
              <span>{formatMoney(v.cents)}</span>
            </div>
          ))}
          <hr style={{ border: 0, borderTop: "1px solid var(--border)", width: "100%" }} />
          <div className="till-row">
            <span>Opening float</span>
            <span>{formatMoney(closed.opening_float_cents)}</span>
          </div>
          <div className="till-row">
            <span>Cash expected</span>
            <span>{formatMoney(expected)}</span>
          </div>
          <div className="till-row">
            <span>Cash counted</span>
            <span>{formatMoney(counted)}</span>
          </div>
          <div className="till-row strong">
            <span>{diff === 0 ? "Balanced" : diff > 0 ? "Over" : "Short"}</span>
            <span className={diff > 0 ? "over" : diff < 0 ? "short" : ""}>{formatMoney(Math.abs(diff))}</span>
          </div>
          <div className="till-panel-actions">
            <button type="button" className="till-btn" onClick={() => window.print()}>
              Print
            </button>
            <button type="button" className="till-btn primary" onClick={onClosed}>
              Done
            </button>
          </div>
        </div>
      </Stage>
    );
  }

  return (
    <Stage title={`Close ${register?.name ?? "register"}`} sub={`Opened ${new Date(shift.opened_at).toLocaleTimeString()}`}>
      <div className="till-panel glass">
        <h2>Count the cash in the drawer</h2>
        <p className="till-text">Count every note and coin, then enter the total. You'll see what was expected after.</p>
        {pendingSales > 0 ? (
          <div className="till-error" style={{ margin: 0 }}>
            {pendingSales} sale{pendingSales === 1 ? " is" : "s are"} still waiting to reach the server. Get back online before closing so
            the count includes {pendingSales === 1 ? "it" : "them"}.
          </div>
        ) : null}
        <div className="till-amount">{formatMoney(amount.cents)}</div>
        <PosNumpad onKey={amount.key} onBackspace={amount.back} />
        <input className="till-input" placeholder="Note (optional), e.g. KSh 200 paid for delivery" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
        {error ? <div className="till-error" style={{ margin: 0 }}>{error}</div> : null}
        <div className="till-panel-actions">
          <button type="button" className="till-btn" onClick={onCancel}>
            Back to selling
          </button>
          <button type="button" className="till-btn primary" disabled={busy || pendingSales > 0} onClick={submit}>
            {busy ? "Closing…" : "Close register"}
          </button>
        </div>
      </div>
    </Stage>
  );
}
