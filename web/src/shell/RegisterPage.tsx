import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { browserSupportsWebAuthn } from "@simplewebauthn/browser";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import { Card } from "../ui/Card";
import { Icon } from "../ui/Icon";

/** Three steps, no password anywhere: submit the org/profile, verify the
 * emailed code (this is what actually creates the account -- see
 * kernel/internal/auth/handlers.go's OtpVerify), then optionally set up
 * a passkey for next time. Skipping passkey setup is fine -- the emailed
 * code always works as a fallback login. */
export function RegisterPage() {
  const { startSignup, verifyCode, addPasskey } = useAuth();
  const navigate = useNavigate();

  const [step, setStep] = useState<"profile" | "code" | "passkey-offer">("profile");
  const [orgName, setOrgName] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmitProfile(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await startSignup(orgName, email, fullName);
      setStep("code");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start signup");
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
      if (browserSupportsWebAuthn()) {
        setStep("passkey-offer");
      } else {
        navigate("/");
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Invalid or expired code");
    } finally {
      setSubmitting(false);
    }
  }

  async function onSetUpPasskey() {
    setError(null);
    setSubmitting(true);
    try {
      await addPasskey();
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not set up a passkey");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", paddingTop: "8vh" }}>
      <Card style={{ width: 380 }}>
        <h1 style={{ fontSize: 20, marginTop: 0 }}>Create your organization</h1>
        {error ? <div className="error-banner">{error}</div> : null}

        {step === "profile" ? (
          <form onSubmit={onSubmitProfile} className="form-grid">
            <FieldWrap label="Organization name" required>
              <Input value={orgName} onChange={(e) => setOrgName(e.target.value)} required autoFocus />
            </FieldWrap>
            <FieldWrap label="Your name">
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </FieldWrap>
            <FieldWrap label="Email" required>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </FieldWrap>
            <Button type="submit" variant="primary" disabled={submitting}>
              {submitting ? "Starting..." : "Continue"}
            </Button>
          </form>
        ) : step === "code" ? (
          <form onSubmit={onVerifyCode} className="form-grid">
            <p className="field-label">We sent a verification code to {email}.</p>
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
              {submitting ? "Verifying..." : "Verify and create organization"}
            </Button>
          </form>
        ) : (
          <div className="form-grid">
            <p className="field-label">
              You're in. Set up a passkey now so you can sign in without an email code next time?
            </p>
            <Button type="button" variant="primary" onClick={onSetUpPasskey} disabled={submitting}>
              <Icon name="key" size={14} /> {submitting ? "Setting up..." : "Set up a passkey"}
            </Button>
            <Button type="button" variant="ghost" onClick={() => navigate("/")} disabled={submitting}>
              Skip for now
            </Button>
          </div>
        )}

        <p className="field-label" style={{ marginTop: 16 }}>
          Already have an account? <Link to="/login">Log in</Link>
          <br />
          Have an invite code? <Link to="/join">Join with an invite</Link>
        </p>
      </Card>
    </div>
  );
}
