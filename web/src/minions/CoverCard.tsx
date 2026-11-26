import { useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { localDay } from "../lib/localTime";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import { PickList } from "../ui/PickList";
import { dayLabel } from "./TimeOff";

interface Cover {
  delegate_user_id: string;
  delegate_name: string;
  starts_on: string;
  ends_on: string;
}

/** Team > While I'm away: who decides my team's requests between two
 * dates. Without cover, requests skip me while I'm on approved time off. */
export function CoverCard() {
  const [cover, setCover] = useState<Cover | null | undefined>(undefined);
  const [people, setPeople] = useState<{ user_id: string; name: string }[]>([]);
  const [who, setWho] = useState("");
  const [from, setFrom] = useState(localDay());
  const [to, setTo] = useState(localDay());
  const [editing, setEditing] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .get<Cover | null>("/api/minions/me/cover")
      .then(setCover)
      .catch(() => setCover(null));
    api
      .get<{ user_id: string; name: string }[]>("/api/minions/meetings/invitable")
      .then(setPeople)
      .catch(() => {});
  }, []);

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!who) return setProblem("Choose who covers for you");
    setBusy(true);
    setProblem(null);
    try {
      setCover(await api.put<Cover>("/api/minions/me/cover", { delegate_user_id: who, starts_on: from, ends_on: to < from ? from : to }));
      setEditing(false);
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    await api.del("/api/minions/me/cover").catch(() => {});
    setCover(null);
  }

  if (cover === undefined) return null;
  return (
    <section aria-label="While I'm away">
      <h2 className="minions-group">While I'm away</h2>
      {cover && !editing ? (
        <div className="minions-row" style={{ background: "var(--surface)", borderRadius: "var(--radius-sm)" }}>
          <div className="minions-row-main">
            <span className="minions-row-title">{cover.delegate_name} decides for you</span>
            <span className="field-label">
              {dayLabel(cover.starts_on)} to {dayLabel(cover.ends_on)}
            </span>
          </div>
          <Button size="sm" variant="ghost" onClick={stop}>
            Stop
          </Button>
        </div>
      ) : null}
      {!cover && !editing ? (
        <div className="minions-actions">
          <Button size="sm" onClick={() => setEditing(true)}>
            Name someone to cover
          </Button>
          <span className="field-label">Without cover, requests skip you while you're on approved time off.</span>
        </div>
      ) : null}
      {editing ? (
        <form className="minions-newclaim" onSubmit={save}>
          <FieldWrap label="Who decides for you" required>
            <PickList aria-label="Who decides for you" placeholder="Search people…" value={who} onChange={setWho} options={people.map((p) => ({ value: p.user_id, label: p.name }))} />
          </FieldWrap>
          <div className="minions-two">
            <FieldWrap label="From" required>
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </FieldWrap>
            <FieldWrap label="To" required>
              <Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
            </FieldWrap>
          </div>
          {problem ? (
            <p className="minions-problem" role="alert">
              {problem}
            </p>
          ) : null}
          <div className="minions-actions">
            <Button type="submit" variant="primary" disabled={busy}>
              Save cover
            </Button>
            <Button variant="ghost" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
