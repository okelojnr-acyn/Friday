import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { browserSupportsWebAuthn } from "@simplewebauthn/browser";
import { markSignedInNow } from "../lib/session";
import { useDemoRoles } from "../lib/demo";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import { Card } from "../ui/Card";
import { Icon } from "../ui/Icon";

/** Passwordless throughout, matching Acyn Wallet's model: a passkey is
 * the primary path (usernameless -- the browser's own picker decides
 * which account, no email prompt), an emailed one-time code is the only
 * fallback. No password field anywhere. */
export function LoginPage() {
  const { loginWithPasskey, requestLoginCode, verifyCode, addPasskey, loginToDemo } = useAuth();
  const demo = useDemoRoles();
  const navigate = useNavigate();

  const [mode, setMode] = useState<"passkey" | "code-email" | "code-entry" | "add-passkey">(
    browserSupportsWebAuthn() ? "passkey" : "code-email",
  );
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onDemo(as: string) {
    setError(null);
    setSubmitting(true);
    try {
      await loginToDemo(as);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't open the demo; try again");
    } finally {
      setSubmitting(false);
    }
  }

  async function onPasskeyLogin() {
    setError(null);
    setSubmitting(true);
    try {
      await loginWithPasskey();
      markSignedInNow();
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not sign in with that passkey");
    } finally {
      setSubmitting(false);
    }
  }

  async function onRequestCode(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await requestLoginCode(email);
      setMode("code-entry");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not send a code");
    } finally {
      setSubmitting(false);
    }
  }

  async function onVerifyCode(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await verifyCode(email, code);
      markSignedInNow();
      // Signed in with a code: no passkey for this address on this device
      // (a new phone, or this Friday moved to a new domain). Offer one.
      if (browserSupportsWebAuthn()) setMode("add-passkey");
      else navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Invalid or expired code");
    } finally {
      setSubmitting(false);
    }
  }

  async function onAddPasskey() {
    setError(null);
    setSubmitting(true);
    try {
      await addPasskey();
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add a passkey");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", paddingTop: "12vh" }}>
      <Card style={{ width: 360 }}>
        <h1 style={{ fontSize: 20, marginTop: 0 }}>{demo ? "Try Friday" : "Log in to Friday"}</h1>
        {error ? <div className="error-banner">{error}</div> : null}
        {demo ? (
          <div className="form-grid" style={{ marginBottom: 12 }}>
            <p className="field-label" style={{ margin: 0 }}>
              A sample shop with its sales, stock, books and staff. Try anything: it all goes back to the start every night.
            </p>
            {demo.map((as) => (
              <Button key={as} type="button" variant={as === "owner" ? "primary" : "secondary"} disabled={submitting} onClick={() => void onDemo(as)}>
                Try as {as.charAt(0).toUpperCase() + as.slice(1)}
              </Button>
            ))}
          </div>
        ) : null}

        {mode === "passkey" ? (
          <div className="form-grid">
            <Button type="button" variant="primary" onClick={onPasskeyLogin} disabled={submitting}>
              <Icon name="key" size={14} /> {submitting ? "Signing in..." : "Continue with a passkey"}
            </Button>
            <p className="field-label" style={{ textAlign: "center", marginTop: 4 }}>
              <a href="#" onClick={(e) => (e.preventDefault(), setMode("code-email"))}>
                Use an email code instead
              </a>
            </p>
          </div>
        ) : mode === "add-passkey" ? (
          <div className="form-grid">
            <p style={{ margin: 0 }}>
              Signed in. Next time, use your fingerprint or face instead of an email code: add a passkey on this device.
            </p>
            <Button type="button" variant="primary" onClick={onAddPasskey} disabled={submitting} autoFocus>
              <Icon name="key" size={14} /> {submitting ? "Adding..." : "Add a passkey"}
            </Button>
            <Button type="button" onClick={() => navigate("/")}>
              Not now
            </Button>
          </div>
        ) : mode === "code-email" ? (
          <form onSubmit={onRequestCode} className="form-grid">
            <FieldWrap label="Email" required>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
            </FieldWrap>
            <Button type="submit" variant="primary" disabled={submitting}>
              {submitting ? "Sending..." : "Email me a code"}
            </Button>
            {browserSupportsWebAuthn() ? (
              <p className="field-label" style={{ textAlign: "center" }}>
                <a href="#" onClick={(e) => (e.preventDefault(), setMode("passkey"))}>
                  Use a passkey instead
                </a>
              </p>
            ) : null}
          </form>
        ) : (
          <form onSubmit={onVerifyCode} className="form-grid">
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
              {submitting ? "Verifying..." : "Verify and log in"}
            </Button>
          </form>
        )}

        <p className="field-label" style={{ marginTop: 16 }}>
          New here? <Link to="/register">Create an organization</Link> or{" "}
          <Link to="/join">join with an invite</Link>
        </p>
      </Card>
    </div>
  );
}
