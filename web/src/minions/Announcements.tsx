import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useAuth } from "../lib/auth";
import { api, ApiError } from "../lib/api";
import { listLocations, type Location } from "../lib/people";
import { useMyPermissions } from "../lib/permissions";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select, Textarea } from "../ui/Field";

interface Announcement {
  id: string;
  title: string;
  body: string;
  author_name: string;
  created_at: string;
  sent_by_me: boolean;
  read: boolean;
  recipients?: number;
  seen?: number;
}

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

/** Today: announcements I haven't read yet, each marked read with one tap. */
export function UnreadAnnouncements() {
  const [list, setList] = useState<Announcement[]>([]);
  useEffect(() => {
    api
      .get<Announcement[]>("/api/minions/announcements")
      .then((as) => setList(as.filter((a) => !a.read)))
      .catch(() => setList([]));
  }, []);
  async function gotIt(a: Announcement) {
    setList((cur) => cur.filter((x) => x.id !== a.id));
    await api.post(`/api/minions/announcements/${a.id}/read`).catch(() => {});
  }
  if (!list.length) return null;
  return (
    <section aria-label="Announcements">
      {list.map((a) => (
        <article key={a.id} className="minions-announcement">
          <p className="field-label">
            From {a.author_name}, {when(a.created_at)}
          </p>
          <h2 className="minions-announcement-title">{a.title}</h2>
          {a.body ? <p className="minions-announcement-body">{a.body}</p> : null}
          <Button size="sm" variant="primary" onClick={() => gotIt(a)}>
            Got it
          </Button>
        </article>
      ))}
    </section>
  );
}

/** Team: send an announcement (my team; a location for managers; anyone
 * for owners), and what I've sent with who has seen it. */
export function SendAnnouncements() {
  const { session } = useAuth();
  const me = useMyPermissions();
  const role = session?.role ?? "member";
  const [sent, setSent] = useState<Announcement[]>([]);
  const [places, setPlaces] = useState<Location[]>([]);
  const [writing, setWriting] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [audience, setAudience] = useState<"team" | "location" | "everyone">("team");
  const [place, setPlace] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [seen, setSeen] = useState<{ name: string; read_at: string | null }[]>([]);

  const load = useCallback(() => {
    api
      .get<Announcement[]>("/api/minions/announcements")
      .then((as) => setSent(as.filter((a) => a.sent_by_me)))
      .catch(() => {});
  }, []);
  useEffect(load, [load]);
  useEffect(() => {
    if (role === "owner" || role === "admin" || role === "branch_manager") listLocations().then(setPlaces).catch(() => {});
  }, [role]);

  const mine = places.filter((p) => role === "owner" || role === "admin" || !me || me.locations.includes("*") || me.locations.includes(p.id));

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!title.trim()) return setProblem("Write what it's about");
    if (audience === "location" && !place) return setProblem("Choose the location");
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/api/minions/announcements", {
        title: title.trim(),
        body: body.trim(),
        audience,
        ...(audience === "location" ? { location_id: place } : {}),
      });
      setWriting(false);
      setTitle("");
      setBody("");
      load();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not send it");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(a: Announcement) {
    if (open === a.id) return setOpen(null);
    setOpen(a.id);
    setSeen(await api.get<{ name: string; read_at: string | null }[]>(`/api/minions/announcements/${a.id}/seen`).catch(() => []));
  }

  return (
    <section aria-label="Announcements">
      <div className="minions-head">
        <h2 className="minions-group">Announcements</h2>
        {!writing ? (
          <Button size="sm" onClick={() => setWriting(true)}>
            Send an announcement
          </Button>
        ) : null}
      </div>
      {writing ? (
        <form className="minions-newclaim" onSubmit={send} aria-label="Send an announcement">
          <FieldWrap label="What it's about" required>
            <Input value={title} maxLength={120} placeholder="e.g. Stock count Saturday 7am" onChange={(e) => setTitle(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Details (optional)">
            <Textarea value={body} maxLength={2000} rows={3} onChange={(e) => setBody(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="To">
            <Select value={audience} onChange={(e) => setAudience(e.target.value as typeof audience)}>
              <option value="team">My team</option>
              {mine.length ? <option value="location">Everyone at a location</option> : null}
              {role === "owner" || role === "admin" ? <option value="everyone">Everyone</option> : null}
            </Select>
          </FieldWrap>
          {audience === "location" ? (
            <FieldWrap label="Location" required>
              <Select value={place} onChange={(e) => setPlace(e.target.value)}>
                <option value="" disabled>
                  Choose…
                </option>
                {mine.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </FieldWrap>
          ) : null}
          {problem ? (
            <p className="minions-problem" role="alert">
              {problem}
            </p>
          ) : null}
          <div className="minions-actions">
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Sending…" : "Send"}
            </Button>
            <Button variant="ghost" onClick={() => setWriting(false)}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
      {sent.length ? (
        <ul className="minions-rows">
          {sent.map((a) => (
            <li key={a.id}>
              <button type="button" className="bell-item" onClick={() => toggle(a)} aria-expanded={open === a.id}>
                <span className="bell-title">{a.title}</span>
                <span className="bell-body">
                  Seen by {a.seen ?? 0} of {a.recipients ?? 0}
                </span>
                <span className="bell-time">{when(a.created_at)}</span>
              </button>
              {open === a.id ? (
                <ul className="minions-seen">
                  {seen.map((s) => (
                    <li key={s.name}>
                      {s.name}: {s.read_at ? `seen ${when(s.read_at)}` : "not yet"}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
