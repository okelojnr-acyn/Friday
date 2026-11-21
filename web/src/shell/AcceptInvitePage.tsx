import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { previewInvite, useAuth, type InvitePreview } from "../lib/auth";
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
  const [params] = useSearchParams();
  const token = params.get("invite");
  return token ? <JoinByLink token={token} /> : <JoinByCode />;
}

/** /join?invite=…: the link an invite emails or someone shares (plan
 * section 12.6). Shows the business and role, asks for a name, joins,
 * signs in, and offers a passkey so the next sign-in is one touch. */
function JoinByLink({ token }: { token: string }) {
  const { acceptInviteLink, addPasskey } = useAuth();
  const navigate = useNavigate();
  const [invite, setInvite] = useState<InvitePreview | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [joined, setJoined] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    previewInvite(token)
      .then((p) => {
        setInvite(p);
        setName(p.full_name);
      })
      .catch((err) => setProblem(err instanceof ApiError ? err.message : "This invite link doesn't work"));
  }, [token]);

  // Team leaders and staff work from the Minions app; the rest in Friday.
  const home = invite && (invite.role === "member" || invite.role === "team_leader") ? "/minions/" : "/";

  async function join(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await acceptInviteLink(token, name.trim());
      setJoined(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not join");
    } finally {
      setBusy(false);
    }
  }

  async function passkey() {
    setError(null);
    try {
      await addPasskey();
      if (home === "/") navigate("/");
      else window.location.href = home;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add a passkey");
    }
  }

  return (
    <div style={{ display: "flex", justifyContent: "center", padding: "8vh 16px 0" }}>
      <Card style={{ width: "min(420px, 100%)" }}>
        {problem ? (
          <>
            <h1 style={{ fontSize: 20, marginTop: 0 }}>This invite can't be used</h1>
            <p>{problem}</p>
            <p className="field-label">
              Already joined? <Link to="/login">Sign in</Link>.
            </p>
          </>
        ) : !invite ? (
          <div className="spinner">Checking your invite…</div>
        ) : joined ? (
          <div className="form-grid">
            <h1 style={{ fontSize: 20, margin: 0 }}>Welcome to {invite.org_name}</h1>
            <p style={{ margin: 0 }}>
              Next time, sign in with your fingerprint or face instead of an email code: add a passkey on this device.
            </p>
            {error ? <div className="error-banner">{error}</div> : null}
            <Button variant="primary" onClick={passkey} autoFocus>
              Add a passkey
            </Button>
            <Button onClick={() => (home === "/" ? navigate("/") : (window.location.href = home))}>Not now</Button>
          </div>
        ) : (
          <form onSubmit={join} className="form-grid">
            <h1 style={{ fontSize: 20, margin: 0 }}>Join {invite.org_name}</h1>
            <p style={{ margin: 0 }}>
              You're invited as {invite.role_words}, with <strong>{invite.email}</strong>.
            </p>
            {error ? <div className="error-banner">{error}</div> : null}
            <FieldWrap label="Your name" required>
              <Input value={name} autoComplete="name" onChange={(e) => setName(e.target.value)} required autoFocus />
            </FieldWrap>
            <Button type="submit" variant="primary" disabled={busy || !name.trim()}>
              {busy ? "Joining…" : "Join"}
            </Button>
          </form>
        )}
      </Card>
    </div>
  );
}

/** The old way: the email and the code an earlier invite sent. Kept for
 * codes sent before invite links. */
function JoinByCode() {
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
