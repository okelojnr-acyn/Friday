import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { browserSupportsWebAuthn } from "@simplewebauthn/browser";
import { useAuth } from "../../lib/auth";
import { ApiError } from "../../lib/api";
import { Button } from "../../ui/Button";
import { FieldWrap, Input } from "../../ui/Field";
import { Card } from "../../ui/Card";
import { Icon } from "../../ui/Icon";
import { Avatar } from "../../ui/Avatar";
import { initials } from "../../ui/resource/fieldFormat";
import { PosPage } from "./PosPage";

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
  if (!session) return <Navigate to="/login" replace />;
  return <PosClockInGate />;
}

function PosClockInGate() {
  const { session, logout } = useAuth();
  const [clockedIn, setClockedIn] = useState(false);

  if (!session) return null;

  if (!clockedIn) {
    return <ClockInScreen onClockedIn={() => setClockedIn(true)} />;
  }

  return (
    <div>
      <header className="topbar">
        <div className="topbar-left">
          <span className="topbar-brand">Friday POS</span>
        </div>
        <div className="topbar-right">
          <span className="topbar-user" title={session.email}>
            <Avatar label={initials(session.email)} title={session.email} size={26} />
            {session.email}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              logout();
              setClockedIn(false);
            }}
            title="Clock out"
          >
            <Icon name="logout" size={16} /> Clock out
          </Button>
        </div>
      </header>
      <PosPage />
    </div>
  );
}

/** `register-fingerprint` is reached only by explicit choice ("New
 * cashier?") -- never auto-triggered on a failed scan. A failed
 * discoverable-login attempt (no matching passkey vs. the OS's own
 * cancel) throws the same generic error either way, so there's no
 * reliable signal to branch on automatically; asking is simpler and
 * more honest than guessing. */
// Passkeys that have worked, or were set up, on this till. Scan offers
// only these, so a broken passkey left in Windows Hello by a set-up that
// failed half way is never offered again (owner, 2026-11-15).
const DEVICE_PASSKEYS_KEY = "friday.pos.device_passkeys";

function devicePasskeys(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(DEVICE_PASSKEYS_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function rememberPasskey(id: string) {
  if (!id) return;
  try {
    const ids = [id, ...devicePasskeys().filter((x) => x !== id)].slice(0, 50);
    localStorage.setItem(DEVICE_PASSKEYS_KEY, JSON.stringify(ids));
  } catch {
    // storage blocked: scan just offers every passkey, as before
  }
}

function forgetPasskey(id: string) {
  try {
    localStorage.setItem(DEVICE_PASSKEYS_KEY, JSON.stringify(devicePasskeys().filter((x) => x !== id)));
  } catch {
    // ignore
  }
}

function ClockInScreen({ onClockedIn }: { onClockedIn: () => void }) {
  const { loginWithPasskey, requestPosCode, verifyPosCode, addPasskey } = useAuth();
  const [mode, setMode] = useState<"scan" | "new-email" | "new-code">("scan");
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

  async function onScan(anyPasskey = false) {
    setError(null);
    setSubmitting(true);
    const known = anyPasskey ? [] : devicePasskeys();
    try {
      rememberPasskey(await loginWithPasskey({ onlyIds: known }));
      onClockedIn();
    } catch (err) {
      if (err instanceof ApiError && err.data.code === "unknown_credential") {
        forgetPasskey(String(err.data.credential_id));
      }
      if (known.length && err instanceof DOMException && err.name === "NotAllowedError") {
        setError(
          "No sign-in from this till was used. If you haven't clocked in on this till before, choose \"Use another passkey\" below.",
        );
      } else {
        setError(passkeyMessage(err, "Could not verify that fingerprint -- try again"));
      }
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
      rememberPasskey(await addPasskey({ platformOnly: true, token }));
      onClockedIn();
    } catch (err) {
      setError(passkeyMessage(err, "Could not verify that code or register your fingerprint"));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", paddingTop: "15vh" }}>
      <Card style={{ width: 380, textAlign: "center" }}>
        <h1 style={{ fontSize: 20, marginTop: 0 }}>Clock in to the register</h1>
        {error ? <div className="error-banner">{error}</div> : null}

        {mode === "scan" ? (
          <div className="form-grid">
            <Button
              type="button"
              variant="primary"
              onClick={() => onScan()}
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
            <p className="field-label">
              <a href="#" onClick={(e) => (e.preventDefault(), onScan(true))}>
                Use another passkey
              </a>
            </p>
            <p className="field-label" style={{ marginTop: 4 }}>
              <a href="#" onClick={(e) => (e.preventDefault(), setMode("new-email"))}>
                New cashier? Set up your fingerprint
              </a>
            </p>
          </div>
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
      </Card>
    </div>
  );
}
