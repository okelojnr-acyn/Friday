import { fullDate } from "../ui/resource/fieldFormat";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  accessRules,
  createInvite,
  listInvites,
  listLocations,
  listPeople,
  PERM_LABEL,
  removePerson,
  revokeInvite,
  ROLE_BLURB,
  ROLE_LABEL,
  RULE_LABEL,
  saveLocation,
  SCOPE_LABEL,
  updatePerson,
  type AccessRules,
  type Invite,
  type Location,
  type Person,
} from "../lib/people";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Drawer } from "../ui/Drawer";
import { AppHint } from "./AppFrame";
import { Checkbox, FieldWrap, Input, Select } from "../ui/Field";

const TABS = [
  ["people", "Everyone"],
  ["invites", "Invites"],
  ["locations", "Locations"],
  ["roles", "Roles & access"],
] as const;
type Tab = (typeof TABS)[number][0];

const ROLES_BELOW_OWNER = ["admin", "branch_manager", "team_leader", "member", "viewer"];
// What a branch manager may hand out (kernel invite_links.go).
const MANAGER_ROLES = ["team_leader", "member"];
const MANAGER_PERMS = ["cashier", "warehouse", "logistics", "purchasing", "sales"];
const PERMS = ["cashier", "warehouse", "logistics", "purchasing", "sales", "accounting", "hr"];

function errText(err: unknown, fallback: string) {
  return err instanceof ApiError ? err.message : fallback;
}

/** Settings > People (plan section 12, step 3): everyone in the business,
 * with their role, jobs, locations and who they report to; invites by
 * role; locations; and what each role can do. Replaces the Admins page. */
export function PeoplePage() {
  const { session } = useAuth();
  const role = session?.role ?? "member";
  const isAdmin = role === "owner" || role === "admin";
  const isManager = role === "branch_manager";
  const [params, setParams] = useSearchParams();
  const raw = params.get("tab");
  const tab: Tab = TABS.some(([id]) => id === raw) ? (raw as Tab) : "people";

  const [people, setPeople] = useState<Person[] | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [locations, setLocations] = useState<Location[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Person | null>(null);
  const [inviting, setInviting] = useState(false);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("");

  function load() {
    listPeople()
      .then(setPeople)
      .catch((err) => {
        setPeople([]);
        setError(errText(err, "Could not load people"));
      });
    listLocations().then(setLocations).catch(() => {});
    if (isAdmin || isManager) listInvites().then(setInvites).catch(() => {});
  }
  useEffect(load, [isAdmin, isManager]);

  const byId = useMemo(() => new Map((people ?? []).map((p) => [p.user_id, p])), [people]);
  const locName = (id: string) => locations.find((l) => l.id === id)?.name ?? "?";
  const q = query.trim().toLowerCase();
  const shown = (people ?? []).filter(
    (p) =>
      (!roleFilter || p.role === roleFilter) &&
      (!q || [p.full_name, p.email, p.staff_id ?? ""].some((s) => s.toLowerCase().includes(q))),
  );
  const pending = invites.filter((i) => i.status === "pending");

  return (
    <div className="page" style={{ maxWidth: 1080 }}>
      <div className="page-header">
        <div>
          <h1 className="page-title">
            {TABS.find(([id]) => id === tab)?.[1]}
            {tab === "invites" && pending.length ? ` (${pending.length} waiting)` : ""}
          </h1>
          <AppHint />
        </div>
        {isAdmin || isManager ? (
          <Button variant="primary" onClick={() => setInviting(true)}>
            Invite someone
          </Button>
        ) : null}
      </div>
      {error ? (
        <div className="error-banner" style={{ marginBottom: 12 }}>
          {error}
        </div>
      ) : null}

      {tab === "people" ? (
        <div className="card">
          <div className="people-filters">
            <Input
              type="search"
              aria-label="Search people"
              placeholder="Search name, email or staff ID"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <Select aria-label="Filter by role" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
              <option value="">Every role</option>
              {["owner", ...ROLES_BELOW_OWNER].map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </Select>
          </div>
          {people === null ? (
            <div className="spinner">Loading…</div>
          ) : shown.length === 0 ? (
            <p className="field-label" style={{ padding: 16 }}>
              Nobody matches.
            </p>
          ) : (
            <div className="table-scroll">
              <table className="table people-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Staff ID</th>
                    <th>Role</th>
                    <th>Jobs</th>
                    <th>Locations</th>
                    <th>Reports to</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((p) => (
                    <tr
                      key={p.user_id}
                      tabIndex={isAdmin ? 0 : -1}
                      onClick={() => isAdmin && setEditing(p)}
                      onKeyDown={(e) => isAdmin && e.key === "Enter" && setEditing(p)}
                      style={{ cursor: isAdmin ? "pointer" : "default" }}
                    >
                      <td>
                        <div style={{ fontWeight: 600 }}>{p.full_name || p.email}</div>
                        {p.full_name ? <div className="field-label">{p.email}</div> : null}
                      </td>
                      <td className="mono">{p.staff_id ?? "—"}</td>
                      <td>
                        <Badge tone={p.role === "owner" ? "accent" : "neutral"}>{ROLE_LABEL[p.role] ?? p.role}</Badge>
                      </td>
                      <td>{p.role === "owner" || p.role === "admin" ? "All" : p.perms.length ? p.perms.join(", ") : "—"}</td>
                      <td>{p.locations.length ? p.locations.map(locName).join(", ") : "All"}</td>
                      <td>{p.reports_to ? (byId.get(p.reports_to)?.full_name || byId.get(p.reports_to)?.email || "—") : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!isAdmin ? (
            <p className="field-label" style={{ padding: "0 16px 16px" }}>
              Owners and admins change people's roles and jobs.
            </p>
          ) : null}
        </div>
      ) : null}

      {tab === "invites" ? (
        <InvitesTab invites={invites} canAct={isAdmin || isManager} onChanged={load} onError={setError} />
      ) : null}
      {tab === "locations" ? (
        <LocationsTab locations={locations} canEdit={isAdmin} onChanged={load} onError={setError} />
      ) : null}
      {tab === "roles" ? <RolesTab /> : null}

      {editing ? (
        <PersonDrawer
          person={editing}
          people={people ?? []}
          locations={locations}
          isOwner={role === "owner"}
          onClose={() => setEditing(null)}
          onSaved={() => (setEditing(null), load())}
        />
      ) : null}
      {inviting ? (
        <InviteDrawer
          people={people ?? []}
          locations={locations}
          managerOnly={isManager}
          myLocations={null}
          onClose={() => setInviting(false)}
          onSent={() => (load(), setParams({ tab: "invites" }, { replace: true }))}
        />
      ) : null}
    </div>
  );
}

function Toggles({
  options,
  labels,
  value,
  onChange,
  disabled,
  legend,
}: {
  options: string[];
  labels: Record<string, string>;
  value: string[];
  onChange: (v: string[]) => void;
  disabled?: boolean;
  legend: string;
}) {
  return (
    <fieldset className="toggle-list" disabled={disabled}>
      <legend className="field-label">{legend}</legend>
      {options.map((o) => (
        <label key={o}>
          <Checkbox
            checked={value.includes(o)}
            onChange={() => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o])}
          />
          <span>{labels[o] ?? o}</span>
        </label>
      ))}
    </fieldset>
  );
}

function PersonDrawer({
  person,
  people,
  locations,
  isOwner,
  onClose,
  onSaved,
}: {
  person: Person;
  people: Person[];
  locations: Location[];
  isOwner: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [role, setRole] = useState(person.role);
  const [perms, setPerms] = useState(person.perms);
  const [locs, setLocs] = useState(person.locations);
  const [boss, setBoss] = useState(person.reports_to ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const holdsAll = role === "owner" || role === "admin";
  const locked = person.role === "owner" && !isOwner;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await updatePerson(person.user_id, { role, perms, locations: locs, reports_to: boss });
      onSaved();
    } catch (err) {
      setError(errText(err, "Could not save"));
      setBusy(false);
    }
  }
  async function remove() {
    if (!window.confirm(`Remove ${person.full_name || person.email} from the business? Their records stay.`)) return;
    setBusy(true);
    try {
      await removePerson(person.user_id);
      onSaved();
    } catch (err) {
      setError(errText(err, "Could not remove"));
      setBusy(false);
    }
  }

  return (
    <Drawer
      title={person.full_name || person.email}
      onClose={onClose}
      footer={
        <>
          <Button variant="danger" onClick={remove} disabled={busy || locked}>
            Remove
          </Button>
          <span style={{ flex: 1 }} />
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={save} disabled={busy || locked}>
            {busy ? "Saving…" : "Save"}
          </Button>
        </>
      }
    >
      {error ? <div className="error-banner">{error}</div> : null}
      <div className="field-label">
        {person.email} · Staff ID <span className="mono">{person.staff_id ?? "—"}</span>
      </div>
      {locked ? <p className="field-label">Only an owner changes another owner.</p> : null}
      <FieldWrap label="Role">
        <Select value={role} onChange={(e) => setRole(e.target.value)} disabled={locked}>
          {(isOwner ? ["owner", ...ROLES_BELOW_OWNER] : ROLES_BELOW_OWNER).map((r) => (
            <option key={r} value={r}>
              {ROLE_LABEL[r]}
            </option>
          ))}
        </Select>
      </FieldWrap>
      {ROLE_BLURB[role] ? <p className="field-label" style={{ margin: 0 }}>{ROLE_BLURB[role]}</p> : null}
      {holdsAll ? (
        <p className="field-label">Owners and admins do every job, at every location.</p>
      ) : (
        <>
          <Toggles legend="Jobs" options={PERMS} labels={PERM_LABEL} value={perms} onChange={setPerms} disabled={locked} />
          <Toggles
            legend="Works at (none ticked: every location)"
            options={locations.map((l) => l.id)}
            labels={Object.fromEntries(locations.map((l) => [l.id, l.name]))}
            value={locs}
            onChange={setLocs}
            disabled={locked}
          />
        </>
      )}
      <FieldWrap label="Reports to">
        <Select value={boss} onChange={(e) => setBoss(e.target.value)} disabled={locked}>
          <option value="">Nobody (approvals go to admins)</option>
          {people
            .filter((p) => p.user_id !== person.user_id && p.role !== "member" && p.role !== "viewer")
            .map((p) => (
              <option key={p.user_id} value={p.user_id}>
                {(p.full_name || p.email) + " · " + ROLE_LABEL[p.role]}
              </option>
            ))}
        </Select>
      </FieldWrap>
    </Drawer>
  );
}

function InviteDrawer({
  people,
  locations,
  managerOnly,
  onClose,
  onSent,
}: {
  people: Person[];
  locations: Location[];
  managerOnly: boolean;
  myLocations: string[] | null;
  onClose: () => void;
  onSent: () => void;
}) {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [role, setRole] = useState("");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [perms, setPerms] = useState<string[]>([]);
  const [locs, setLocs] = useState<string[]>([]);
  const [boss, setBoss] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<Invite | null>(null);
  const roles = managerOnly ? MANAGER_ROLES : ROLES_BELOW_OWNER;
  const perms_ = managerOnly ? MANAGER_PERMS : PERMS;
  const holdsAll = role === "admin";
  const emailOk = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim());

  async function send() {
    setBusy(true);
    setError(null);
    try {
      const inv = await createInvite({ email: email.trim(), full_name: name.trim(), role, perms, locations: locs, reports_to: boss });
      setSent(inv);
      setStep(3);
      onSent();
    } catch (err) {
      setError(errText(err, "Could not send the invite"));
    } finally {
      setBusy(false);
    }
  }

  const steps = ["Role", "Details", "Send"];
  return (
    <Drawer
      title="Invite someone"
      onClose={onClose}
      footer={
        sent ? (
          <Button variant="primary" onClick={onClose}>
            Done
          </Button>
        ) : (
          <>
            {step > 1 ? (
              <Button onClick={() => setStep((s) => (s - 1) as 1 | 2)} disabled={busy}>
                Back
              </Button>
            ) : null}
            <span style={{ flex: 1 }} />
            {step === 1 ? (
              <Button variant="primary" disabled={!role} onClick={() => setStep(2)}>
                Next
              </Button>
            ) : (
              <Button variant="primary" disabled={!emailOk || busy || (managerOnly && !locs.length)} onClick={send}>
                {busy ? "Sending…" : "Send invite"}
              </Button>
            )}
          </>
        )
      }
    >
      <ol className="stepper" aria-label="Invite steps">
        {steps.map((s, i) => (
          <li key={s} className={i + 1 === step ? "now" : i + 1 < step ? "done" : ""} aria-current={i + 1 === step ? "step" : undefined}>
            {s}
          </li>
        ))}
      </ol>
      {error ? <div className="error-banner">{error}</div> : null}

      {step === 1 ? (
        <div className="role-cards" role="radiogroup" aria-label="Role">
          {roles.map((r) => (
            <button
              key={r}
              type="button"
              role="radio"
              aria-checked={role === r}
              className={`role-card${role === r ? " selected" : ""}`}
              onClick={() => setRole(r)}
            >
              <strong>{ROLE_LABEL[r]}</strong>
              <span>{ROLE_BLURB[r]}</span>
            </button>
          ))}
        </div>
      ) : null}

      {step === 2 ? (
        <>
          <FieldWrap label="Email" required>
            <Input type="email" autoComplete="off" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          </FieldWrap>
          <FieldWrap label="Name">
            <Input autoComplete="off" value={name} onChange={(e) => setName(e.target.value)} />
          </FieldWrap>
          {holdsAll || role === "viewer" ? null : (
            <>
              <Toggles legend="Jobs" options={perms_} labels={PERM_LABEL} value={perms} onChange={setPerms} />
              <Toggles
                legend={managerOnly ? "Works at (required)" : "Works at (none ticked: every location)"}
                options={locations.map((l) => l.id)}
                labels={Object.fromEntries(locations.map((l) => [l.id, l.name]))}
                value={locs}
                onChange={setLocs}
              />
              <FieldWrap label="Reports to">
                <Select value={boss} onChange={(e) => setBoss(e.target.value)}>
                  <option value="">{managerOnly ? "Me" : "Nobody (approvals go to admins)"}</option>
                  {people
                    .filter((p) => p.role !== "member" && p.role !== "viewer")
                    .map((p) => (
                      <option key={p.user_id} value={p.user_id}>
                        {(p.full_name || p.email) + " · " + ROLE_LABEL[p.role]}
                      </option>
                    ))}
                </Select>
              </FieldWrap>
            </>
          )}
        </>
      ) : null}

      {step === 3 && sent ? (
        <div style={{ display: "grid", gap: 12 }}>
          <p style={{ margin: 0 }}>
            Invite sent to <strong>{sent.email}</strong> as {ROLE_LABEL[sent.role]}. The link works once, for 7 days.
          </p>
          {sent.link ? (
            <>
              <FieldWrap label="Or share the link yourself">
                <Input readOnly value={sent.link} onFocus={(e) => e.currentTarget.select()} />
              </FieldWrap>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <Button onClick={() => navigator.clipboard?.writeText(sent.link!)}>Copy link</Button>
                <a
                  className="btn btn-secondary"
                  href={`https://wa.me/?text=${encodeURIComponent(`Join us on Friday: ${sent.link}`)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Share on WhatsApp
                </a>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
    </Drawer>
  );
}

function InvitesTab({
  invites,
  canAct,
  onChanged,
  onError,
}: {
  invites: Invite[];
  canAct: boolean;
  onChanged: () => void;
  onError: (e: string) => void;
}) {
  if (!canAct) return <p className="field-label">Owners, admins and branch managers see invites.</p>;
  if (!invites.length) return <p className="field-label">No invites in the last 30 days.</p>;
  const tone = (s: Invite["status"]) => (s === "accepted" ? "success" : s === "pending" ? "accent" : "neutral");
  return (
    <div className="card table-scroll">
      <table className="table">
        <thead>
          <tr>
            <th>Email</th>
            <th>Role</th>
            <th>Status</th>
            <th>Expires</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {invites.map((i) => (
            <tr key={i.id} style={{ cursor: "default" }}>
              <td>
                <div style={{ fontWeight: 600 }}>{i.full_name || i.email}</div>
                {i.full_name ? <div className="field-label">{i.email}</div> : null}
              </td>
              <td>{ROLE_LABEL[i.role]}</td>
              <td>
                <Badge tone={tone(i.status)}>{i.status}</Badge>
              </td>
              <td>{i.status === "pending" ? fullDate(i.expires_at, false) : "—"}</td>
              <td style={{ textAlign: "right" }}>
                {i.status === "pending" ? (
                  <Button
                    size="sm"
                    onClick={() =>
                      revokeInvite(i.id)
                        .then(onChanged)
                        .catch((err) => onError(errText(err, "Could not revoke")))
                    }
                  >
                    Revoke
                  </Button>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LocationsTab({
  locations,
  canEdit,
  onChanged,
  onError,
}: {
  locations: Location[];
  canEdit: boolean;
  onChanged: () => void;
  onError: (e: string) => void;
}) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Location["kind"]>("store");
  const [busy, setBusy] = useState(false);
  async function add() {
    setBusy(true);
    try {
      await saveLocation({ name: name.trim(), kind, address: "" });
      setName("");
      onChanged();
    } catch (err) {
      onError(errText(err, "Could not add the location"));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card card-padded form-grid">
      <p className="field-label" style={{ margin: 0, maxWidth: "60ch" }}>
        Stores, warehouses and offices. People can be limited to some of them; a branch manager sees only theirs.
      </p>
      <ul className="location-list">
        {locations.map((l) => (
          <li key={l.id}>
            <strong>{l.name}</strong> <span className="field-label">· {l.kind}</span>
          </li>
        ))}
      </ul>
      {canEdit ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <FieldWrap label="New location">
            <Input value={name} maxLength={80} placeholder="Westlands" onChange={(e) => setName(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Kind">
            <Select value={kind} onChange={(e) => setKind(e.target.value as Location["kind"])}>
              <option value="store">Store</option>
              <option value="warehouse">Warehouse</option>
              <option value="office">Office</option>
              <option value="other">Other</option>
            </Select>
          </FieldWrap>
          <Button variant="primary" disabled={busy || !name.trim()} onClick={add}>
            Add
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function RolesTab() {
  const [rules, setRules] = useState<AccessRules | null>(null);
  useEffect(() => {
    accessRules().then(setRules).catch(() => {});
  }, []);
  if (!rules) return <div className="spinner">Loading…</div>;
  const roles = rules.roles;
  const cell = (spec?: string) => {
    if (!spec) return <span aria-label="no">—</span>;
    const [scope, need] = spec.split("+");
    return (
      <span>
        {SCOPE_LABEL[scope] ?? scope}
        {need ? <span className="field-label"> (if {need.split("|").join(" or ")})</span> : null}
      </span>
    );
  };
  return (
    <div className="card table-scroll">
      <table className="table roles-table">
        <caption className="field-label" style={{ textAlign: "left", padding: 12 }}>
          What each role can do, and where. Jobs in brackets are ticked per person. The same table is what Friday enforces.
        </caption>
        <thead>
          <tr>
            <th scope="col">Can…</th>
            {roles.map((r) => (
              <th key={r} scope="col">
                {ROLE_LABEL[r]}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Object.keys(rules.rules)
            .sort()
            .map((rule) => (
              <tr key={rule} style={{ cursor: "default" }}>
                <th scope="row">{RULE_LABEL[rule] ?? rule}</th>
                {roles.map((r) => (
                  <td key={r}>{cell(rules.rules[rule][r])}</td>
                ))}
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
