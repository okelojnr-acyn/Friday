import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { localDay } from "../lib/localTime";
import { formatMoney, useOrgSettings } from "../lib/orgSettings";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";

interface Deal {
  id: string;
  contact_name: string;
  contact_email: string;
  company: string;
  stage: "new" | "qualified" | "proposition" | "won" | "lost";
  value_cents: number;
  currency: string;
  next_step_at: string | null;
}

const NEXT: Record<string, { stage: Deal["stage"]; label: string }> = {
  new: { stage: "qualified", label: "They're interested" },
  qualified: { stage: "proposition", label: "Sent an offer" },
};
const STAGE_WORDS: Record<string, string> = { new: "New lead", qualified: "Interested", proposition: "Offer sent" };
const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Sales work: my open deals, follow-ups first (late ones marked), one
 * tap to the next stage, won or lost (with why), a note on the deal's
 * history, and adding a lead. CRM's rules decide which deals are mine. */
export function SalesWork() {
  const [deals, setDeals] = useState<Deal[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    api
      .get<Deal[]>("/api/crm/opportunities")
      .then((ds) => setDeals(ds.filter((d) => d.stage !== "won" && d.stage !== "lost")))
      .catch((err) => setError(errorText(err, "Could not load your deals")));
  }, []);
  useEffect(load, [load]);

  async function change(d: Deal, patch: Partial<Deal> & { lost_reason?: string }) {
    setError(null);
    try {
      await api.patch(`/api/crm/opportunities/${d.id}`, patch);
      load();
    } catch (err) {
      setError(errorText(err, "Could not save the deal"));
    }
  }

  const sorted = [...(deals ?? [])].sort(
    (a, b) => (a.next_step_at ? new Date(a.next_step_at).getTime() : Infinity) - (b.next_step_at ? new Date(b.next_step_at).getTime() : Infinity),
  );

  return (
    <>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <section aria-label="My deals">
        <div className="minions-head">
          <h2 className="minions-group">My deals</h2>
          <Button size="sm" variant={adding ? "ghost" : "primary"} onClick={() => setAdding((a) => !a)}>
            {adding ? "Close" : "Add a lead"}
          </Button>
        </div>
        {adding ? (
          <NewLead
            onAdded={() => {
              setAdding(false);
              load();
            }}
            onError={setError}
          />
        ) : null}
        {deals === null && !error ? <div className="spinner">Loading…</div> : null}
        {deals && deals.length === 0 ? (
          <div className="minions-empty">
            <p className="minions-empty-title">No open deals</p>
            <p className="field-label">Met someone who might buy? Add them as a lead.</p>
          </div>
        ) : null}
        <ul className="minions-cardlist">
          {sorted.map((d) => (
            <DealCard key={d.id} deal={d} onChange={change} onError={setError} />
          ))}
        </ul>
      </section>
    </>
  );
}

function DealCard({
  deal: d,
  onChange,
  onError,
}: {
  deal: Deal;
  onChange: (d: Deal, patch: Partial<Deal> & { lost_reason?: string }) => Promise<void>;
  onError: (m: string | null) => void;
}) {
  const [note, setNote] = useState("");
  const [losing, setLosing] = useState(false);
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const late = d.next_step_at && new Date(d.next_step_at).getTime() < Date.now();
  const next = NEXT[d.stage];

  async function addNote() {
    if (!note.trim()) return;
    setBusy(true);
    try {
      await api.post("/api/crm/activities", { opportunity_id: d.id, body: note.trim() });
      setNote("");
    } catch (err) {
      onError(errorText(err, "Could not save the note"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="minions-parcel">
      <p className="minions-row-title">
        {d.contact_name}
        {d.company ? `, ${d.company}` : ""}
      </p>
      <p className="field-label">
        {STAGE_WORDS[d.stage] ?? d.stage}
        {d.value_cents ? `, ${formatMoney(d.value_cents, { currency: d.currency, whole: true })}` : ""}
      </p>
      <p className={late ? "minions-flag" : "field-label"}>
        {d.next_step_at
          ? `${late ? "Follow-up was due" : "Follow up"} ${new Date(d.next_step_at).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })}`
          : "No follow-up set"}
      </p>
      {d.contact_email ? (
        <div className="minions-actions">
          <a className="btn btn-secondary btn-sm" href={`mailto:${d.contact_email}`}>
            Email {d.contact_email}
          </a>
        </div>
      ) : null}
      <FieldWrap label="Follow up on">
        <Input
          type="date"
          value={d.next_step_at ? localDay(new Date(d.next_step_at)) : ""}
          onChange={(e) => e.target.value && void onChange(d, { next_step_at: new Date(`${e.target.value}T09:00`).toISOString() })}
        />
      </FieldWrap>
      <div className="minions-two">
        <Input value={note} maxLength={500} placeholder="What happened? e.g. Called, wants a quote" onChange={(e) => setNote(e.target.value)} />
        <Button size="sm" disabled={busy || !note.trim()} onClick={addNote}>
          Add note
        </Button>
      </div>
      {losing ? (
        <div className="minions-fix">
          <FieldWrap label="Why was it lost?" required>
            <Input value={why} maxLength={200} placeholder="e.g. Bought elsewhere, too expensive" onChange={(e) => setWhy(e.target.value)} />
          </FieldWrap>
          <div className="minions-actions">
            <Button size="sm" disabled={!why.trim()} onClick={() => onChange(d, { stage: "lost", lost_reason: why.trim() })}>
              Mark lost
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setLosing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="minions-actions">
          {next ? (
            <Button size="sm" onClick={() => onChange(d, { stage: next.stage })}>
              {next.label}
            </Button>
          ) : null}
          <Button size="sm" variant="primary" onClick={() => onChange(d, { stage: "won" })}>
            Won
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setLosing(true)}>
            Lost
          </Button>
        </div>
      )}
    </li>
  );
}

function NewLead({ onAdded, onError }: { onAdded: () => void; onError: (m: string | null) => void }) {
  const { currency } = useOrgSettings();
  const [name, setName] = useState("");
  const [company, setCompany] = useState("");
  const [email, setEmail] = useState("");
  const [value, setValue] = useState("");
  const [follow, setFollow] = useState("");
  const [busy, setBusy] = useState(false);

  async function add(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) {
      onError("Who is it? Add their name");
      return;
    }
    setBusy(true);
    onError(null);
    try {
      await api.post("/api/crm/opportunities", {
        contact_name: name.trim(),
        company: company.trim(),
        contact_email: email.trim(),
        value_cents: Math.round((Number.parseFloat(value || "0") || 0) * 100),
        currency, // the business's, not CRM's USD default
        ...(follow ? { next_step_at: new Date(`${follow}T09:00`).toISOString() } : {}),
      });
      onAdded();
    } catch (err) {
      onError(errorText(err, "Could not add the lead"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="minions-newclaim" onSubmit={add} aria-label="Add a lead">
      <FieldWrap label="Name" required>
        <Input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
      </FieldWrap>
      <FieldWrap label="Business (optional)">
        <Input value={company} maxLength={120} onChange={(e) => setCompany(e.target.value)} />
      </FieldWrap>
      <FieldWrap label="Email (optional)">
        <Input type="email" value={email} maxLength={200} onChange={(e) => setEmail(e.target.value)} />
      </FieldWrap>
      <div className="minions-two">
        <FieldWrap label={`Worth about (${currency})`}>
          <Input value={value} inputMode="decimal" onChange={(e) => setValue(e.target.value)} />
        </FieldWrap>
        <FieldWrap label="Follow up on">
          <Input type="date" value={follow} onChange={(e) => setFollow(e.target.value)} />
        </FieldWrap>
      </div>
      <Button type="submit" variant="primary" disabled={busy}>
        {busy ? "Adding…" : "Add lead"}
      </Button>
    </form>
  );
}
