import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import {
  listLocations,
  PERM_LABEL,
  ROLE_LABEL,
  type Location,
} from "../lib/people";
import { useMyPermissions } from "../lib/permissions";
import { useOrgSettings } from "../lib/orgSettings";
import { Button } from "../ui/Button";

/** Me: who I am at this business (name, staff ID, role, jobs, where I
 * work), the till if I'm a cashier, a passkey for one-touch sign-in, and
 * sign out. */
export function MePage() {
  const { session, logout, addPasskey } = useAuth();
  const me = useMyPermissions();
  const [locations, setLocations] = useState<Location[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const business = useOrgSettings().name;
  useEffect(() => {
    listLocations()
      .then(setLocations)
      .catch(() => {});
  }, []);
  if (!session) return null;
  const where =
    !me || me.locations.includes("*")
      ? "Every location"
      : me.locations
          .map((id) => locations.find((l) => l.id === id)?.name ?? "—")
          .join(", ");

  return (
    <div className="page minions-page">
      <h1 className="page-title">Me</h1>
      <section className="minions-pass" aria-label="Staff pass">
        <p className="minions-pass-business">{business || "Staff pass"}</p>
        <p className="minions-pass-id" aria-label="Staff ID">
          {me?.staff_id ?? "—"}
        </p>
        <p className="minions-pass-name">{session.email}</p>
        <p className="minions-pass-role">
          {ROLE_LABEL[me?.role ?? session.role] ?? session.role}
        </p>
        <p className="minions-pass-where">Works at {where}</p>
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

      <section
        className="card card-padded"
        style={{ display: "grid", gap: 10 }}
      >
        {notice ? (
          <div className="field-label" role="status">
            {notice}
          </div>
        ) : null}
        <Button
          onClick={() =>
            addPasskey()
              .then(() =>
                setNotice(
                  "Passkey added: next time, sign in with your fingerprint or face.",
                ),
              )
              .catch((e) =>
                setNotice(
                  e instanceof Error ? e.message : "Could not add a passkey",
                ),
              )
          }
        >
          Add a passkey on this phone
        </Button>
        <Link className="btn btn-secondary" to="/devices">
          Passkeys and where I'm signed in
        </Link>
        <Button variant="ghost" onClick={logout}>
          Sign out
        </Button>
      </section>
    </div>
  );
}
