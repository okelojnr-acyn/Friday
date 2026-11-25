import { useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";

export interface Person {
  user_id: string;
  name: string;
}

/** Team > Give a task: to someone down my line (the server checks it and
 * tells them). A due day means that day's close of business. */
export function GiveTask({ people, onGiven }: { people: Person[]; onGiven: () => void }) {
  const [to, setTo] = useState("");
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function give(e: FormEvent) {
    e.preventDefault();
    if (!to) return setProblem("Choose who it's for");
    if (!title.trim()) return setProblem("Say what needs doing");
    setProblem(null);
    setDone(null);
    setBusy(true);
    try {
      await api.post("/api/projects/tasks", {
        title: title.trim(),
        assignee_user_id: to,
        ...(due ? { due_at: due } : {}),
      });
      setDone(`Given to ${people.find((p) => p.user_id === to)?.name ?? "them"}. They've been told.`);
      setTitle("");
      setDue("");
      onGiven();
    } catch (err) {
      setProblem(err instanceof ApiError ? err.message : "Could not give the task");
    } finally {
      setBusy(false);
    }
  }

  if (people.length === 0) return null;
  return (
    <form className="minions-newclaim" onSubmit={give} aria-label="Give a task">
      <FieldWrap label="For" required>
        <Select value={to} onChange={(e) => setTo(e.target.value)}>
          <option value="" disabled>
            Choose a person…
          </option>
          {people.map((p) => (
            <option key={p.user_id} value={p.user_id}>
              {p.name}
            </option>
          ))}
        </Select>
      </FieldWrap>
      <FieldWrap label="What needs doing" required>
        <Input value={title} maxLength={200} placeholder="e.g. Count shelf 4" onChange={(e) => setTitle(e.target.value)} />
      </FieldWrap>
      <FieldWrap label="Due (optional)">
        <Input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
      </FieldWrap>
      {problem ? (
        <p className="minions-problem" role="alert">
          {problem}
        </p>
      ) : null}
      {done ? (
        <p className="field-label" role="status">
          {done}
        </p>
      ) : null}
      <Button type="submit" variant="primary" disabled={busy}>
        {busy ? "Giving…" : "Give task"}
      </Button>
    </form>
  );
}
