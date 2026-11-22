import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import { listLocations, PERM_LABEL, ROLE_LABEL, type Location } from "../lib/people";
import { useMyPermissions } from "../lib/permissions";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";

/** Me: who I am at this business (name, staff ID, role, jobs, where I
 * work), the till if I'm a cashier, a passkey for one-touch sign-in, and
 * sign out. */
export function MePage() {
  const { session, logout, addPasskey } = useAuth();
  const me = useMyPermissions();
  const [locations, setLocations] = useState<Location[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    listLocations().then(setLocations).catch(() => {});
  }, []);
  if (!session) return null;
  const where =
    !me || me.locations.includes("*")
      ? "Every location"
      : me.locations.map((id) => locations.find((l) => l.id === id)?.name ?? "—").join(", ");

  return (
    <div className="page minions-page">
      <h1 className="page-title">Me</h1>
      <section className="card card-padded minions-id" aria-label="Staff card">
        <div className="field-label">Staff ID</div>
        <div className="minions-staff-id">{me?.staff_id ?? "—"}</div>
        <div style={{ fontWeight: 600 }}>{session.email}</div>
        <div>
          <Badge tone="accent">{ROLE_LABEL[me?.role ?? session.role] ?? session.role}</Badge>
        </div>
        <div className="field-label">Works at: {where}</div>
      </section>

      {me && me.perms.length ? (
        <section className="card card-padded">
          <h2 className="minions-h2">My jobs</h2>
          <ul className="minions-list">
            {me.perms.map((p) => (
              <li key={p}>{PERM_LABEL[p] ?? p}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {me?.rules["pos.sell"] ? (
        <a className="btn btn-primary minions-cta" href="/pos.html">
          Open the till
        </a>
      ) : null}

      <section className="card card-padded" style={{ display: "grid", gap: 10 }}>
        {notice ? <div className="field-label" role="status">{notice}</div> : null}
        <Button
          onClick={() =>
            addPasskey()
              .then(() => setNotice("Passkey added: next time, sign in with your fingerprint or face."))
              .catch((e) => setNotice(e instanceof Error ? e.message : "Could not add a passkey"))
          }
        >
          Add a passkey on this phone
        </Button>
        <Button variant="ghost" onClick={logout}>
          Sign out
        </Button>
      </section>
    </div>
  );
}
