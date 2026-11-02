import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import { Card } from "../ui/Card";

export function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const [orgName, setOrgName] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register(orgName, email, password, fullName);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create your organization");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", paddingTop: "8vh" }}>
      <Card style={{ width: 380 }}>
        <h1 style={{ fontSize: 20, marginTop: 0 }}>Create your organization</h1>
        <form onSubmit={onSubmit} className="form-grid">
          {error ? <div className="error-banner">{error}</div> : null}
          <FieldWrap label="Organization name" required>
            <Input value={orgName} onChange={(e) => setOrgName(e.target.value)} required autoFocus />
          </FieldWrap>
          <FieldWrap label="Your name">
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Email" required>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </FieldWrap>
          <FieldWrap label="Password" required>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              required
            />
          </FieldWrap>
          <Button type="submit" variant="primary" disabled={submitting}>
            {submitting ? "Creating..." : "Create organization"}
          </Button>
        </form>
        <p className="field-label" style={{ marginTop: 16 }}>
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </Card>
    </div>
  );
}
