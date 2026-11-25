import { MyTimeOff, WhosAway } from "./TimeOff";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { localDay } from "../lib/localTime";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";

interface Attendee {
  user_id: string;
  name: string;
  response: "invited" | "accepted" | "declined";
}
interface Meeting {
  id: string;
  title: string;
  starts_at: string;
  ends_at: string;
  created_by_name?: string;
  created_by_email: string;
  attendees?: Attendee[];
  /** "organiser", my answer, or "" (an older Minions: unknown). */
  my_role?: string;
}
interface Task {
  id: string;
  title: string;
  status: string;
  due_at: string | null;
}
type Item = { at: Date; kind: "meeting"; m: Meeting } | { at: Date; kind: "task"; t: Task };

const DAYS = 14;
const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);
const time = (d: Date) => d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });

/** Calendar: my next two weeks, one list by day: meetings I organise or am
 * invited to (answer them here) and when my tasks are due. Times are in my
 * own time zone. New meeting invites people I look after or report to. */
export function CalendarPage() {
  const [meetings, setMeetings] = useState<Meeting[] | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    const end = new Date(start.getTime() + DAYS * 86_400_000);
    api
      .get<Meeting[]>(`/api/minions/meetings?mine=true&start=${start.toISOString()}&end=${end.toISOString()}`)
      .then(setMeetings)
      .catch((err) => setError(errorText(err, "Could not load your meetings")));
    api
      .get<Task[]>("/api/projects/tasks?mine=true")
      .then(setTasks)
      .catch(() => {});
  }, []);
  useEffect(load, [load]);

  async function answer(m: Meeting, response: "accepted" | "declined") {
    setError(null);
    try {
      const updated = await api.post<Meeting>(`/api/minions/meetings/${m.id}/respond`, { response });
      setMeetings((cur) => (cur ?? []).map((x) => (x.id === m.id ? updated : x)));
    } catch (err) {
      setError(errorText(err, "Could not send your answer"));
    }
  }

  async function cancel(m: Meeting) {
    setError(null);
    try {
      await api.del(`/api/minions/meetings/${m.id}`);
      setMeetings((cur) => (cur ?? []).filter((x) => x.id !== m.id));
    } catch (err) {
      setError(errorText(err, "Could not cancel the meeting"));
    }
  }

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const until = today.getTime() + DAYS * 86_400_000;
  const items: Item[] = [
    ...(meetings ?? []).map((m) => ({ at: new Date(m.starts_at), kind: "meeting" as const, m })),
    ...tasks
      .filter((t) => t.status !== "done" && t.due_at)
      .map((t) => ({ at: new Date(String(t.due_at)), kind: "task" as const, t }))
      .filter((i) => i.at.getTime() >= today.getTime() && i.at.getTime() < until),
  ].sort((a, b) => a.at.getTime() - b.at.getTime());
  const byDay = new Map<string, Item[]>();
  for (const i of items) byDay.set(localDay(i.at), [...(byDay.get(localDay(i.at)) ?? []), i]);

  return (
    <div className="page minions-page">
      <header className="minions-head">
        <h1 className="page-title">Calendar</h1>
        <Button size="sm" variant={adding ? "ghost" : "primary"} onClick={() => setAdding((a) => !a)}>
          {adding ? "Close" : "New meeting"}
        </Button>
      </header>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      {adding ? (
        <NewMeeting
          onMade={() => {
            setAdding(false);
            load();
          }}
        />
      ) : null}

      <WhosAway />
      <MyTimeOff />

      {meetings === null && !error ? <div className="spinner">Loading your calendar…</div> : null}
      {meetings && items.length === 0 ? (
        <div className="minions-empty">
          <p className="minions-empty-title">Nothing in the next two weeks</p>
          <p className="field-label">Meetings you're invited to and tasks with a due date show up here.</p>
        </div>
      ) : null}

      {[...byDay.entries()].map(([day, list]) => (
        <section key={day} aria-label={day}>
          <h2 className="minions-group">
            {day === localDay()
              ? "Today"
              : new Date(`${day}T12:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })}
          </h2>
          <ul className="minions-rows">
            {list.map((i) =>
              i.kind === "meeting" ? (
                <li key={`m-${i.m.id}`} className="minions-row minions-claimrow">
                  <span className="minions-time">{time(i.at)}</span>
                  <div className="minions-row-main">
                    <span className="minions-row-title">{i.m.title}</span>
                    <span className="field-label">
                      Until {time(new Date(i.m.ends_at))}
                      {i.m.my_role === "organiser"
                        ? `, ${(i.m.attendees ?? []).filter((a) => a.response === "accepted").length} of ${(i.m.attendees ?? []).length} coming`
                        : `, from ${i.m.created_by_name || i.m.created_by_email}`}
                    </span>
                    <div className="minions-actions">
                      {i.m.my_role === "organiser" ? (
                        <Button size="sm" variant="ghost" onClick={() => cancel(i.m)}>
                          Cancel meeting
                        </Button>
                      ) : i.m.my_role ? (
                        <>
                          <Button
                            size="sm"
                            variant={i.m.my_role === "accepted" ? "primary" : "secondary"}
                            aria-pressed={i.m.my_role === "accepted"}
                            onClick={() => answer(i.m, "accepted")}
                          >
                            {i.m.my_role === "accepted" ? "Coming" : "Accept"}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            aria-pressed={i.m.my_role === "declined"}
                            onClick={() => answer(i.m, "declined")}
                          >
                            {i.m.my_role === "declined" ? "Not coming" : "Decline"}
                          </Button>
                        </>
                      ) : null}
                    </div>
                  </div>
                </li>
              ) : (
                <li key={`t-${i.t.id}`} className="minions-row">
                  <span className="minions-time">{time(i.at)}</span>
                  <div className="minions-row-main">
                    <span className="minions-row-title">{i.t.title}</span>
                    <span className="field-label">Task due</span>
                  </div>
                </li>
              ),
            )}
          </ul>
        </section>
      ))}
    </div>
  );
}

function NewMeeting({ onMade }: { onMade: () => void }) {
  const [people, setPeople] = useState<{ user_id: string; name: string }[]>([]);
  const [title, setTitle] = useState("");
  const [day, setDay] = useState(localDay());
  const [at, setAt] = useState("10:00");
  const [minutes, setMinutes] = useState("60");
  const [invited, setInvited] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<{ user_id: string; name: string }[]>("/api/minions/meetings/invitable")
      .then(setPeople)
      .catch(() => setPeople([]));
  }, []);

  async function make(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return setProblem("Give the meeting a name");
    const start = new Date(`${day}T${at}`); // local time
    if (Number.isNaN(start.getTime())) return setProblem("Pick a day and time");
    setProblem(null);
    setBusy(true);
    try {
      await api.post("/api/minions/meetings", {
        title: title.trim(),
        starts_at: start.toISOString(),
        ends_at: new Date(start.getTime() + Number(minutes) * 60_000).toISOString(),
        attendee_user_ids: invited,
      });
      onMade();
    } catch (err) {
      setProblem(errorText(err, "Could not make the meeting"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="minions-newclaim" onSubmit={make} aria-label="New meeting">
      <FieldWrap label="What" required>
        <Input value={title} maxLength={200} placeholder="e.g. Weekly stock count" onChange={(e) => setTitle(e.target.value)} />
      </FieldWrap>
      <div className="minions-two">
        <FieldWrap label="Day" required>
          <Input type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        </FieldWrap>
        <FieldWrap label="Time" required>
          <Input type="time" value={at} onChange={(e) => setAt(e.target.value)} />
        </FieldWrap>
      </div>
      <FieldWrap label="How long">
        <Select value={minutes} onChange={(e) => setMinutes(e.target.value)}>
          <option value="15">15 minutes</option>
          <option value="30">30 minutes</option>
          <option value="60">1 hour</option>
          <option value="90">1 hour 30</option>
          <option value="120">2 hours</option>
        </Select>
      </FieldWrap>
      {people.length ? (
        <fieldset className="minions-invite">
          <legend>Invite</legend>
          {people.map((p) => (
            <label key={p.user_id}>
              <input
                type="checkbox"
                checked={invited.includes(p.user_id)}
                onChange={(e) =>
                  setInvited((cur) => (e.target.checked ? [...cur, p.user_id] : cur.filter((u) => u !== p.user_id)))
                }
              />
              {p.name}
            </label>
          ))}
        </fieldset>
      ) : null}
      {problem ? (
        <p className="minions-problem" role="alert">
          {problem}
        </p>
      ) : null}
      <Button type="submit" variant="primary" disabled={busy}>
        {busy ? "Sending…" : invited.length ? "Send invites" : "Add to my calendar"}
      </Button>
    </form>
  );
}
