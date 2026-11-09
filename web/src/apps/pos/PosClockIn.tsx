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
function ClockInScreen({ onClockedIn }: { onClockedIn: () => void }) {
  const { loginWithPasskey, requestPosCode, verifyPosCode, addPasskey } = useAuth();
  const [mode, setMode] = useState<"scan" | "new-email" | "new-code">("scan");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onScan() {
    setError(null);
    setSubmitting(true);
    try {
      await loginWithPasskey();
      onClockedIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not verify that fingerprint -- try again");
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
      await verifyPosCode(email, code, fullName);
      await addPasskey({ platformOnly: true });
      onClockedIn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not verify that code or register your fingerprint");
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
              onClick={onScan}
              disabled={submitting || !browserSupportsWebAuthn()}
            >
              <Icon name="key" size={14} /> {submitting ? "Verifying..." : "Scan to clock in"}
            </Button>
            {!browserSupportsWebAuthn() ? (
              <p className="field-label">This device/browser doesn't support passkeys.</p>
            ) : null}
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
          </form>
        )}
      </Card>
    </div>
  );
}
