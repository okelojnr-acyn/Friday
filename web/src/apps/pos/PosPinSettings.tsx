import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import {
  clearPosPin,
  forgetThisTill,
  listPosDevices,
  listPosPinEvents,
  listPosPins,
  myPosPin,
  posDeviceId,
  posDeviceToken,
  revokePosDevice,
  setMyPosPin,
  setPosPinFor,
  trustThisTill,
  unlockPosPin,
  type PosCashier,
  type PosDevice,
  type PosPinEvent,
} from "../../lib/posPin";

const EVENT_LABEL: Record<string, string> = {
  signin: "signed in with PIN",
  wrong_pin: "wrong PIN",
  locked: "PIN locked (5 wrong)",
  unlocked: "PIN unlocked",
  pin_set: "PIN set",
  pin_cleared: "PIN removed",
  device_enrolled: "till trusted",
  device_revoked: "till no longer trusted",
};

function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function errText(err: unknown, fallback: string) {
  return err instanceof ApiError ? err.message : fallback;
}

/** "Cashier PIN" sheet from the till menu. Everyone on a full session can
 * set their own PIN; owners and admins also trust this till, manage
 * people's PINs and see PIN activity. A PIN session sees an explanation
 * only: PIN changes need the fingerprint. */
export function PosPinSettings({ onClose }: { onClose: () => void }) {
  const { session } = useAuth();
  const viaPin = session ? tokenVia(session.token) === "pos" : false;
  const manager = !viaPin && (session?.role === "owner" || session?.role === "admin");

  return (
    <div className="till-sheet-backdrop" onClick={onClose}>
      <div className="till-panel glass till-sheet till-pin-sheet" onClick={(e) => e.stopPropagation()}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0, fontSize: 22 }}>Cashier PIN</h2>
          <button type="button" className="till-chip glass" style={{ cursor: "pointer" }} onClick={onClose}>
            Done
          </button>
        </div>
        {viaPin ? (
          <p className="till-text">
            You signed in with your PIN. To change PINs or trust this till, clock in with your fingerprint.
          </p>
        ) : (
          <>
            <MyPin />
            {manager ? <ManagerPanel /> : null}
          </>
        )}
      </div>
    </div>
  );
}

function tokenVia(token: string): string | undefined {
  try {
    const part = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return (JSON.parse(atob(part)) as { via?: string }).via;
  } catch {
    return undefined;
  }
}

function PinInput({ onSubmit, label }: { onSubmit: (pin: string) => Promise<void>; label: string }) {
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!/^\d{6}$/.test(pin)) return setMsg({ ok: false, text: "A PIN is exactly 6 digits." });
    if (pin !== again) return setMsg({ ok: false, text: "The two PINs don't match." });
    setBusy(true);
    setMsg(null);
    try {
      await onSubmit(pin);
      setPin("");
      setAgain("");
      setMsg({ ok: true, text: "PIN saved." });
    } catch (err) {
      setMsg({ ok: false, text: errText(err, "Could not save the PIN") });
    } finally {
      setBusy(false);
    }
  }

  const field = (v: string, set: (s: string) => void, ph: string) => (
    <input
      className="till-pin-input"
      type="password"
      inputMode="numeric"
      autoComplete="off"
      maxLength={6}
      placeholder={ph}
      value={v}
      onChange={(e) => set(e.target.value.replace(/\D/g, ""))}
    />
  );
  return (
    <form onSubmit={submit} className="till-pin-form">
      {field(pin, setPin, "6 digits")}
      {field(again, setAgain, "Again")}
      <button type="submit" className="till-btn primary" disabled={busy}>
        {busy ? "Saving…" : label}
      </button>
      {msg ? <span className={msg.ok ? "till-pin-ok" : "till-pin-err"}>{msg.text}</span> : null}
    </form>
  );
}

function MyPin() {
  const [has, setHas] = useState<boolean | null>(null);
  useEffect(() => {
    myPosPin().then((r) => setHas(r.has_pin)).catch(() => setHas(null));
  }, []);
  return (
    <section className="till-pin-section">
      <h3>My PIN</h3>
      <p className="till-text">
        {has ? "You have a PIN. Set a new one to change it." : "For when the fingerprint doesn't work, on a till a manager trusted."}
      </p>
      <PinInput label={has ? "Change my PIN" : "Set my PIN"} onSubmit={async (p) => (await setMyPosPin(p), setHas(true))} />
    </section>
  );
}

function ManagerPanel() {
  const [devices, setDevices] = useState<PosDevice[]>([]);
  const [people, setPeople] = useState<PosCashier[]>([]);
  const [events, setEvents] = useState<PosPinEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tillName, setTillName] = useState("Till");
  const [settingFor, setSettingFor] = useState<string | null>(null);
  const [trusted, setTrusted] = useState(!!posDeviceToken());
  const thisId = posDeviceId();

  const load = useCallback(async () => {
    try {
      const [d, p, e] = await Promise.all([listPosDevices(), listPosPins(), listPosPinEvents()]);
      setDevices(d);
      setPeople(p);
      setEvents(e);
    } catch (err) {
      setError(errText(err, "Could not load PIN settings"));
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  const act = (fn: () => Promise<unknown>) => async () => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(errText(err, "That didn't work"));
    }
  };

  return (
    <>
      {error ? <div className="error-banner">{error}</div> : null}
      <section className="till-pin-section">
        <h3>This till</h3>
        {trusted ? (
          <p className="till-text">Trusted: cashiers can sign in here with their PIN.</p>
        ) : (
          <div className="till-pin-form">
            <input className="till-pin-input wide" value={tillName} onChange={(e) => setTillName(e.target.value)} placeholder="Till name" />
            <button
              type="button"
              className="till-btn primary"
              onClick={act(async () => (await trustThisTill(tillName), setTrusted(true)))}
            >
              Trust this till for PIN sign-in
            </button>
          </div>
        )}
        {devices.length ? (
          <ul className="till-pin-list">
            {devices.map((d) => (
              <li key={d.id}>
                <span>
                  <b>{d.name}</b>
                  {d.id === thisId ? " (this till)" : ""}
                  <small>
                    {d.revoked_at ? ` · removed ${when(d.revoked_at)}` : d.last_used_at ? ` · last PIN sign-in ${when(d.last_used_at)}` : " · no PIN sign-in yet"}
                  </small>
                </span>
                {!d.revoked_at ? (
                  <button
                    type="button"
                    className="till-chip glass"
                    onClick={act(async () => {
                      await revokePosDevice(d.id);
                      if (d.id === thisId) {
                        forgetThisTill();
                        setTrusted(false);
                      }
                    })}
                  >
                    Stop trusting
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="till-pin-section">
        <h3>People</h3>
        <ul className="till-pin-list">
          {people.map((p) => (
            <li key={p.user_id}>
              <span>
                <b>{p.name || p.email}</b>
                <small>
                  {" "}
                  · {p.has_pin ? (p.locked_until ? `locked until ${new Date(p.locked_until).toLocaleTimeString([], { timeStyle: "short" })}` : "has a PIN") : "no PIN"}
                </small>
              </span>
              <span style={{ display: "flex", gap: 6 }}>
                {p.locked_until ? (
                  <button type="button" className="till-chip glass" onClick={act(() => unlockPosPin(p.user_id))}>
                    Unlock
                  </button>
                ) : null}
                <button type="button" className="till-chip glass" onClick={() => setSettingFor(settingFor === p.user_id ? null : p.user_id)}>
                  {p.has_pin ? "Reset PIN" : "Set PIN"}
                </button>
                {p.has_pin ? (
                  <button type="button" className="till-chip glass" onClick={act(() => clearPosPin(p.user_id))}>
                    Remove
                  </button>
                ) : null}
              </span>
              {settingFor === p.user_id ? (
                <div style={{ flexBasis: "100%" }}>
                  <PinInput
                    label="Save PIN"
                    onSubmit={async (pin) => {
                      await setPosPinFor(p.user_id, pin);
                      setSettingFor(null);
                      await load();
                    }}
                  />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </section>

      <section className="till-pin-section">
        <h3>Recent PIN activity</h3>
        {events.length === 0 ? <p className="till-text">Nothing yet.</p> : null}
        <ul className="till-pin-list compact">
          {events.slice(0, 30).map((e, i) => (
            <li key={i}>
              <span>
                {e.name ? <b>{e.name}</b> : null} {EVENT_LABEL[e.kind] ?? e.kind}
                {e.device ? <small> · {e.device}</small> : null}
              </span>
              <small>{when(e.created_at)}</small>
            </li>
          ))}
        </ul>
      </section>
    </>
  );
}
