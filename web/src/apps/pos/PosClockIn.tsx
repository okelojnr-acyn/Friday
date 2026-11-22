import { IdleLock, IDLE_MS } from "./IdleLock";
import { fetchMyPermissions, forgetMyPermissions } from "../../lib/permissions";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { browserSupportsWebAuthn } from "@simplewebauthn/browser";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { Button } from "../../ui/Button";
import { FieldWrap, Input } from "../../ui/Field";
import { Icon } from "../../ui/Icon";
import { listPosCashiers, posDeviceToken, type PosCashier } from "../../lib/posPin";
import { PosTill } from "./PosTill";

/** The auth gate *and* the biometric cashier clock-in gate, deliberately
 * one component -- a shared register device means "is there a valid
 * session" and "who's actually standing here right now" are two
 * different questions (unlike the main shell, where they're the same).
 * `clockedIn` is in-memory only, reset on every page load: walking up
 * to the register (or reloading after an update) always demands a
 * fresh scan, regardless of whatever session AuthProvider restored from
 * localStorage -- that session might belong to whoever used this
 * tablet last, not whoever's here now.
 *
 * loginWithPasskey() is the actual clock-in: it's the same discoverable
 * ceremony the main LoginPage uses, which resolves the scanned
 * credential to an account server-side and overwrites the active
 * session with a freshly issued JWT for *that* person -- so every POS
 * request made afterward (open a shift, ring up a sale) is already
 * correctly authenticated as whoever just scanned in. No separate
 * "active cashier" concept needed; the session already is the cashier.
 */
export function RequirePosAuth() {
  const { session, ready } = useAuth();
  if (!ready) return <div className="page spinner">Loading...</div>;
  // A till trusted for PIN sign-in shows the clock-in screen even with
  // nobody signed in; any other device starts at the normal sign-in.
  if (!session && !posDeviceToken()) return <Navigate to="/login" replace />;
  return <PosClockInGate />;
}

function PosClockInGate() {
  const { session, logout } = useAuth();
  // `npm run dev` only: /pos.html?preview skips the passkey, for looking
  // at the till's screens against a local mock. Never in a build.
  const [clockedIn, setClockedIn] = useState(
    import.meta.env.DEV && new URLSearchParams(window.location.search).has("preview"),
  );
  const [refused, setRefused] = useState<string | null>(null);
  const [locked, setLocked] = useState(false);
  const lastActive = useRef(Date.now());

  // Only someone who may sell clocks in at the till (plan 20.3): owners
  // and managers, and staff with the cashier job. The apps refuse a sale
  // anyway; this says so at the door. An older kernel that can't answer
  // lets them in.
  async function admit() {
    forgetMyPermissions();
    const me = await fetchMyPermissions().catch(() => null);
    if (me && !me.rules["pos.sell"]) {
      logout();
      setRefused("Only cashiers can clock in at the till. A manager can tick the cashier job for you in People.");
      return;
    }
    setRefused(null);
    lastActive.current = Date.now();
    setClockedIn(true);
  }

  function clockOut() {
    logout();
    setLocked(false);
    setClockedIn(false);
  }

  // Idle for IDLE_MS: lock over the open order until the same cashier's PIN.
  useEffect(() => {
    if (!clockedIn) return;
    const seen = () => {
      lastActive.current = Date.now();
    };
    const events = ["pointerdown", "keydown", "touchstart"] as const;
    events.forEach((e) => window.addEventListener(e, seen, { passive: true }));
    const t = window.setInterval(() => {
      if (Date.now() - lastActive.current > IDLE_MS) setLocked(true);
    }, 15_000);
    return () => {
      events.forEach((e) => window.removeEventListener(e, seen));
      window.clearInterval(t);
    };
  }, [clockedIn]);

  if (!clockedIn || !session) {
    return <ClockInScreen onClockedIn={admit} refused={refused} />;
  }

  return (
    <>
      <PosTill
        onClockOut={clockOut}
        // One cashier never sells on another's session: switching clocks
        // this one out first (the open register stays open).
        onSwitchCashier={clockOut}
      />
      {locked ? (
        <IdleLock
          email={session.email}
          onResume={() => {
            lastActive.current = Date.now();
            setLocked(false);
          }}
          onClockOut={clockOut}
        />
      ) : null}
    </>
  );
}

/** `register-fingerprint` is reached only by explicit choice ("New
 * cashier?") -- never auto-triggered on a failed scan. A failed
 * discoverable-login attempt (no matching passkey vs. the OS's own
 * cancel) throws the same generic error either way, so there's no
 * reliable signal to branch on automatically; asking is simpler and
 * more honest than guessing. */
function ClockInScreen({ onClockedIn, refused }: { onClockedIn: () => void; refused?: string | null }) {
  const { loginWithPasskey, requestPosCode, verifyPosCode, addPasskey } = useAuth();
  const trusted = !!posDeviceToken();
  const [mode, setMode] = useState<"scan" | "new-email" | "new-code" | "pin">(
    trusted && !browserSupportsWebAuthn() ? "pin" : "scan",
  );
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // The browser's own passkey errors carry the real reason. POS asks for
  // the till's built-in fingerprint/face sign-in only, so on a computer
  // without it (e.g. Windows without Windows Hello) creation fails before
  // any password manager is offered. Say so instead of "try again".
  function passkeyMessage(err: unknown, fallback: string): string {
    if (err instanceof ApiError) return err.message;
    const name = err instanceof DOMException ? err.name : "";
    if (name === "NotSupportedError" || name === "SecurityError") {
      return "This device can't create a fingerprint sign-in. Set up its built-in fingerprint or face sign-in (Windows Hello, Touch ID or the phone's own), or use a till device that has one.";
    }
    if (name === "NotAllowedError") {
      return "The fingerprint step was cancelled or timed out. If no fingerprint or face prompt appeared, this device's built-in sign-in (Windows Hello, Touch ID) isn't set up.";
    }
    if (name === "InvalidStateError") {
      return "This device already has a fingerprint sign-in for this account. Use Scan to clock in.";
    }
    return fallback;
  }

  async function onScan() {
    setError(null);
    setSubmitting(true);
    try {
      await loginWithPasskey();
      onClockedIn();
    } catch (err) {
      setError(passkeyMessage(err, "Could not verify that fingerprint -- try again"));
    } finally {
      setSubmitting(false);
    }
  }

  async function onRequestCode(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await requestPosCode(email);
      setMode("new-code");
    } catch (err) {
      // A 404 here means the honest thing: no account, and no pending
      // admin invite either -- see PosRequestCode's own doc comment.
      setError(err instanceof ApiError ? err.message : "Could not send a code");
    } finally {
      setSubmitting(false);
    }
  }

  async function onVerifyAndRegister(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      // Pass the cashier's own new token: `addPasskey` from this render
      // still holds the till's previous session (often the owner's
      // Friday Host sign-in), which registered the fingerprint to the
      // wrong person, or failed outright (owner report, 2026-11-15).
      const token = await verifyPosCode(email, code, fullName);
      await addPasskey({ platformOnly: true, token });
      onClockedIn();
    } catch (err) {
      setError(passkeyMessage(err, "Could not verify that code or register your fingerprint"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="till-stage">
      <div className="till-stage-head">
        <span />
        <div className="till-stage-title">Clock in</div>
        <span />
      </div>
      <div className="till-stage-center">
      <div className="till-panel glass" style={{ textAlign: "center", fontSize: 16 }}>
        <p className="till-text" style={{ marginTop: 0 }}>Use this till's fingerprint, face or Windows Hello PIN.</p>
        {refused ? <div className="error-banner" role="alert">{refused}</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}

        {mode === "scan" ? (
          <div className="form-grid">
            <Button
              type="button"
              variant="primary"
              onClick={onScan}
              disabled={submitting || !browserSupportsWebAuthn()}
            >
              <Icon name="key" size={14} /> {submitting ? "Verifying..." : "Scan to clock in"}
            </Button>
            {!browserSupportsWebAuthn() ? (
              <p className="field-label">This device/browser doesn't support passkeys.</p>
            ) : null}
            <p className="field-label">
              Fingerprint not working? Use your Windows Hello PIN in the same prompt.
            </p>
            {trusted ? (
              <Button type="button" onClick={() => (setError(null), setMode("pin"))} disabled={submitting}>
                <Icon name="shield-check" size={14} /> Use my cashier PIN
              </Button>
            ) : null}
            <p className="field-label" style={{ marginTop: 4 }}>
              <a href="#" onClick={(e) => (e.preventDefault(), setMode("new-email"))}>
                New cashier? Set up your fingerprint
              </a>
            </p>
          </div>
        ) : mode === "pin" ? (
          <PinSignIn onClockedIn={onClockedIn} onBack={() => (setError(null), setMode("scan"))} />
        ) : mode === "new-email" ? (
          <form onSubmit={onRequestCode} className="form-grid">
            <FieldWrap label="Your email" required>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            </FieldWrap>
            <FieldWrap label="Your name (if this is your first time)">
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </FieldWrap>
            <Button type="submit" variant="primary" disabled={submitting}>
              {submitting ? "Sending..." : "Email me a code"}
            </Button>
            <p className="field-label">
              Only works for an email your admin has already added to the team.
            </p>
            <p className="field-label">
              <a href="#" onClick={(e) => (e.preventDefault(), setMode("scan"))}>
                Back to scan
              </a>
            </p>
          </form>
        ) : (
          <form onSubmit={onVerifyAndRegister} className="form-grid">
            <p className="field-label">Code sent to {email}.</p>
            <FieldWrap label="6-digit code" required>
              <Input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                inputMode="numeric"
                maxLength={6}
                required
                autoFocus
              />
            </FieldWrap>
            <Button type="submit" variant="primary" disabled={submitting}>
              {submitting ? "Verifying..." : "Verify and register fingerprint"}
            </Button>
            <p className="field-label">
              Fingerprint not working? Use your Windows Hello PIN in the same prompt.
            </p>
          </form>
        )}
      </div>
      </div>
      <div />
    </div>
  );
}

/** Pick your name, then type your 6-digit PIN. Works only on a till a
 * manager trusted; the session reaches selling and shifts only. */
function PinSignIn({ onClockedIn, onBack }: { onClockedIn: () => void; onBack: () => void }) {
  const { loginWithPin } = useAuth();
  const [people, setPeople] = useState<PosCashier[] | null>(null);
  const [who, setWho] = useState<PosCashier | null>(null);
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    listPosCashiers()
      .then((p) => {
        setPeople(p);
        if (p.length === 1) setWho(p[0]);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the cashiers"));
  }, []);

  async function submit(full: string) {
    if (!who) return;
    setBusy(true);
    setError(null);
    try {
      await loginWithPin(who.user_id, full);
      onClockedIn();
    } catch (err) {
      setPin("");
      if (err instanceof ApiError) {
        const left = (err.data as { tries_left?: number } | undefined)?.tries_left;
        setError(left !== undefined ? `Wrong PIN. ${left} ${left === 1 ? "try" : "tries"} left.` : err.message);
      } else {
        setError("Could not sign in");
      }
    } finally {
      setBusy(false);
    }
  }

  function press(k: string) {
    if (busy || pin.length >= 6) return;
    const next = pin + k;
    setPin(next);
    if (next.length === 6) submit(next);
  }

  const back = (
    <p className="field-label" style={{ marginTop: 4 }}>
      <a href="#" onClick={(e) => (e.preventDefault(), who && people && people.length > 1 ? (setWho(null), setPin(""), setError(null)) : onBack())}>
        {who && people && people.length > 1 ? "Not you? Pick your name" : "Back to fingerprint"}
      </a>
    </p>
  );

  if (!who) {
    return (
      <div className="form-grid">
        {error ? <div className="error-banner">{error}</div> : null}
        {people === null && !error ? <p className="till-text">Loading…</p> : null}
        {people && people.length === 0 ? (
          <p className="till-text">
            Nobody has a PIN yet. Clock in with your fingerprint, then choose “Set my PIN” in the till menu.
          </p>
        ) : null}
        <div className="till-pin-people">
          {people?.map((p) => (
            <button key={p.user_id} type="button" className="till-pin-person glass" onClick={() => setWho(p)}>
              <span className="till-pin-avatar">{p.name.slice(0, 1).toUpperCase()}</span>
              {p.name}
              {p.locked_until ? <span className="till-pin-locked">Locked</span> : null}
            </button>
          ))}
        </div>
        {back}
      </div>
    );
  }

  return (
    <div className="form-grid">
      <p className="till-text" style={{ margin: 0, fontWeight: 600 }}>{who.name}</p>
      {error ? <div className="error-banner">{error}</div> : null}
      <div className="till-pin-dots" aria-label={`${pin.length} of 6 digits`}>
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className={i < pin.length ? "on" : ""} />
        ))}
      </div>
      <div className="till-pin-pad">
        {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((k) => (
          <button key={k} type="button" className="till-key" disabled={busy} onClick={() => press(k)}>
            {k}
          </button>
        ))}
        <button type="button" className="till-key" disabled={busy || !pin} onClick={() => setPin("")} aria-label="Clear">
          C
        </button>
        <button type="button" className="till-key" disabled={busy} onClick={() => press("0")}>
          0
        </button>
        <button type="button" className="till-key" disabled={busy || !pin} onClick={() => setPin((p) => p.slice(0, -1))} aria-label="Delete">
          ⌫
        </button>
      </div>
      {back}
    </div>
  );
}
