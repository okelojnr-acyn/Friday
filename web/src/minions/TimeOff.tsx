import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { localDay } from "../lib/localTime";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";

export interface TimeOffItem {
  id: string;
  kind: "annual" | "sick" | "unpaid";
  starts_on: string;
  ends_on: string;
  days: number;
  note: string;
  status: "submitted" | "approved" | "rejected" | "withdrawn";
  waiting_on_name: string;
  decision_note: string;
  employee_name: string;
}
interface Balance {
  annual_days: number;
  annual_taken: number;
  annual_left: number;
  sick_taken: number;
}

const KIND: Record<TimeOffItem["kind"], string> = { annual: "Annual leave", sick: "Sick leave", unpaid: "Unpaid leave" };
const STATUS: Record<TimeOffItem["status"], string> = {
  submitted: "Waiting for a decision",
  approved: "Approved",
  rejected: "Turned down",
  withdrawn: "You took it back",
};
export const dayLabel = (iso: string) =>
  new Date(`${iso}T12:00:00`).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
const span = (t: TimeOffItem) => (t.starts_on === t.ends_on ? dayLabel(t.starts_on) : `${dayLabel(t.starts_on)} to ${dayLabel(t.ends_on)}`);
const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Who's away in the next two weeks (people I can see: my team, my
 * locations, everyone for owners), from approved time off. */
export function WhosAway() {
  const [away, setAway] = useState<TimeOffItem[]>([]);
  useEffect(() => {
    const start = new Date();
    const end = new Date(start.getTime() + 14 * 86_400_000);
    api
      .get<TimeOffItem[]>(`/api/minions/time_off?start=${localDay(start)}&end=${localDay(end)}`)
      .then((ts) => setAway(ts.filter((t) => t.status === "approved")))
      .catch(() => setAway([]));
  }, []);
  if (!away.length) return null;
  return (
    <section aria-label="Who's away">
      <h2 className="minions-group">Who's away</h2>
      <ul className="minions-rows">
        {away.map((t) => (
          <li key={t.id} className="minions-row">
            <div className="minions-row-main">
              <span className="minions-row-title">{t.employee_name}</span>
              <span className="field-label">
                {KIND[t.kind]}, {span(t)}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

/** My time off: what's left this year, ask for days, and where my
 * requests are. */
export function MyTimeOff() {
  const [mine, setMine] = useState<TimeOffItem[] | null>(null);
  const [balance, setBalance] = useState<Balance | null>(null);
  const [asking, setAsking] = useState(false);
  const [kind, setKind] = useState<TimeOffItem["kind"]>("annual");
  const [from, setFrom] = useState(localDay());
  const [to, setTo] = useState(localDay());
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<TimeOffItem[]>("/api/minions/time_off?mine=true")
      .then(setMine)
      .catch(() => setMine([]));
    api
      .get<Balance>("/api/minions/time_off/balance")
      .then(setBalance)
      .catch(() => {});
  }, []);
  useEffect(load, [load]);

  async function ask(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/api/minions/time_off", { kind, starts_on: from, ends_on: to < from ? from : to, note: note.trim() });
      setAsking(false);
      setNote("");
      load();
    } catch (err) {
      setProblem(errorText(err, "Could not send the request"));
    } finally {
      setBusy(false);
    }
  }

  async function takeBack(t: TimeOffItem) {
    try {
      await api.post(`/api/minions/time_off/${t.id}/withdraw`);
      load();
    } catch (err) {
      setProblem(errorText(err, "Could not take it back"));
    }
  }

  if (mine === null) return null;
  const today = localDay();
  const recent = mine.filter((t) => t.ends_on >= today || t.status === "submitted").slice(0, 8);
  return (
    <section aria-label="My time off">
      <div className="minions-head">
        <h2 className="minions-group">My time off</h2>
        {!asking ? (
          <Button size="sm" onClick={() => setAsking(true)}>
            Ask for time off
          </Button>
        ) : null}
      </div>
      {balance ? (
        <p className="field-label" style={{ margin: "0 0 8px" }}>
          {balance.annual_left} of {balance.annual_days} annual days left this year
          {balance.sick_taken ? `, ${balance.sick_taken} sick ${balance.sick_taken === 1 ? "day" : "days"} taken` : ""}
        </p>
      ) : null}
      {asking ? (
        <form className="minions-newclaim" onSubmit={ask} aria-label="Ask for time off">
          <fieldset className="minions-choice" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
            <legend>What kind</legend>
            {(["annual", "sick", "unpaid"] as const).map((k) => (
              <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)}>
                {KIND[k].replace(" leave", "")}
              </button>
            ))}
          </fieldset>
          <div className="minions-two">
            <FieldWrap label="First day" required>
              <Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </FieldWrap>
            <FieldWrap label="Last day" required>
              <Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
            </FieldWrap>
          </div>
          <FieldWrap label="Note (optional)">
            <Input value={note} maxLength={300} placeholder={kind === "sick" ? "e.g. Doctor's note to follow" : "e.g. Family visit"} onChange={(e) => setNote(e.target.value)} />
          </FieldWrap>
          {problem ? (
            <p className="minions-problem" role="alert">
              {problem}
            </p>
          ) : null}
          <div className="minions-actions">
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Sending…" : "Send request"}
            </Button>
            <Button variant="ghost" onClick={() => setAsking(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
      {!asking && problem ? (
        <p className="minions-problem" role="alert">
          {problem}
        </p>
      ) : null}
      {recent.length ? (
        <ul className="minions-rows">
          {recent.map((t) => (
            <li key={t.id} className="minions-row">
              <div className="minions-row-main">
                <span className="minions-row-title">
                  {KIND[t.kind]}, {t.days} {t.days === 1 ? "day" : "days"}
                </span>
                <span className="field-label">
                  {span(t)}. {STATUS[t.status]}
                  {t.status === "submitted" && t.waiting_on_name ? ` (${t.waiting_on_name})` : ""}
                  {t.status === "rejected" && t.decision_note ? `: ${t.decision_note}` : ""}
                </span>
              </div>
              {t.status === "submitted" || (t.status === "approved" && t.starts_on > today) ? (
                <Button size="sm" variant="ghost" onClick={() => takeBack(t)}>
                  Take back
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

/** Team: time off waiting for my decision. */
export function WaitingTimeOff({ Decision }: { Decision: (p: { item: { id: string }; onDone: () => void }) => JSX.Element }) {
  const [list, setList] = useState<TimeOffItem[]>([]);
  const load = useCallback(() => {
    api
      .get<TimeOffItem[]>("/api/minions/time_off?waiting=true")
      .then(setList)
      .catch(() => setList([]));
  }, []);
  useEffect(load, [load]);
  if (!list.length) return null;
  return (
    <section aria-label="Time off waiting for you">
      <h2 className="minions-group">Time off waiting for you</h2>
      <ul className="minions-cardlist">
        {list.map((t) => (
          <li key={t.id} className="minions-parcel">
            <p className="minions-row-title">
              {t.employee_name}: {KIND[t.kind]}, {t.days} {t.days === 1 ? "day" : "days"}
            </p>
            <p className="field-label">
              {span(t)}
              {t.note ? `. ${t.note}` : ""}
            </p>
            <Decision item={t} onDone={load} />
          </li>
        ))}
      </ul>
    </section>
  );
}
