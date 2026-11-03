import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import { Card } from "../ui/Card";

/** The other half of Settings > Members' invite flow: finishes joining
 * an existing org from the code an admin's invite emailed, instead of
 * creating a brand new one (see RegisterPage for that path, and
 * kernel/internal/auth/invites.go's AcceptInvite for the server side --
 * same emailed-one-time-code shape, different payload). */
export function AcceptInvitePage() {
  const { acceptInvite } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await acceptInvite(email, code, fullName);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Invalid or expired code");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", paddingTop: "8vh" }}>
      <Card style={{ width: 380 }}>
        <h1 style={{ fontSize: 20, marginTop: 0 }}>Join with an invite</h1>
        {error ? <div className="error-banner">{error}</div> : null}
        <form onSubmit={onSubmit} className="form-grid">
          <p className="field-label">
            Enter the email an admin invited and the code they sent you.
          </p>
          <FieldWrap label="Email" required>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </FieldWrap>
          <FieldWrap label="Your name">
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Invite code" required>
            <Input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              maxLength={6}
              required
            />
          </FieldWrap>
          <Button type="submit" variant="primary" disabled={submitting}>
            {submitting ? "Joining..." : "Join"}
          </Button>
        </form>
        <p className="field-label" style={{ marginTop: 16 }}>
          No invite? <Link to="/register">Create a new organization</Link> or <Link to="/login">log in</Link>.
        </p>
      </Card>
    </div>
  );
}
