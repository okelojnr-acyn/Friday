import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { listRecords, updateRecord } from "../lib/resourceApi";
import type { RecordRow } from "../lib/types";

/** Next step for a task, tapped from the list: to do -> doing -> done. */
const NEXT: Record<string, { status: string; label: string }> = {
  todo: { status: "in_progress", label: "Start" },
  in_progress: { status: "done", label: "Done" },
  done: { status: "todo", label: "Reopen" },
};

const dayStart = (d: Date) =>
  new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();

function dueGroup(
  task: RecordRow,
  today: number,
): "overdue" | "today" | "later" | "done" {
  if (task.status === "done") return "done";
  if (!task.due_at) return "later";
  const due = dayStart(new Date(String(task.due_at)));
  return due < today ? "overdue" : due === today ? "today" : "later";
}

const GROUPS = [
  ["overdue", "Overdue"],
  ["today", "Due today"],
  ["later", "Coming up"],
  ["done", "Done"],
] as const;

/** Today: the day strip (date, what's left) and my tasks by when they're
 * due, each one tap from its next step. Minions reads Projects' tasks
 * directly; "mine" is the assignee email (a real person link is HR plan
 * phase 4). */
export function MyTasksPage() {
  const { session } = useAuth();
  const [tasks, setTasks] = useState<RecordRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    listRecords("projects", "task")
      .then(setTasks)
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : "Could not load your tasks",
        ),
      );
  }, []);

  async function advance(task: RecordRow) {
    const next = NEXT[String(task.status)] ?? NEXT.todo;
    setBusy(task.id);
    setError(null);
    try {
      const updated = await updateRecord("projects", "task", task.id, {
        status: next.status,
      });
      setTasks((cur) =>
        (cur ?? []).map((t) => (t.id === task.id ? updated : t)),
      );
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not update the task",
      );
    } finally {
      setBusy(null);
    }
  }

  const now = new Date();
  const today = dayStart(now);
  const email = session?.email.toLowerCase() ?? "";
  const mine = (tasks ?? []).filter(
    (t) => String(t.assignee_email ?? "").toLowerCase() === email,
  );
  const open = mine.filter((t) => t.status !== "done");
  const overdue = open.filter((t) => dueGroup(t, today) === "overdue").length;
  const hour = now.getHours();
  const greeting =
    hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";

  return (
    <div className="page minions-page">
      <section className="minions-daystrip" aria-label="Your day">
        <p className="minions-daystrip-date">
          {now.toLocaleDateString(undefined, {
            weekday: "long",
            day: "numeric",
            month: "long",
          })}
        </p>
        <h1 className="minions-daystrip-title">{greeting}</h1>
        {tasks ? (
          <p className="minions-daystrip-sum">
            {open.length === 0
              ? "Nothing left on your list."
              : `${open.length} ${open.length === 1 ? "task" : "tasks"} to do${overdue ? `, ${overdue} overdue` : ""}.`}
          </p>
        ) : null}
      </section>

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      {!tasks && !error ? (
        <div className="spinner">Loading your tasks…</div>
      ) : null}

      {tasks && mine.length === 0 ? (
        <div className="minions-empty">
          <p className="minions-empty-title">No tasks for you yet</p>
          <p className="field-label">
            Tasks your manager gives you show up here, with when they're due.
          </p>
        </div>
      ) : null}

      {GROUPS.map(([key, label]) => {
        const rows = mine.filter((t) => dueGroup(t, today) === key);
        if (!rows.length) return null;
        return (
          <section key={key} aria-label={label}>
            <h2
              className={`minions-group${key === "overdue" ? " danger" : ""}`}
            >
              {label}
            </h2>
            <ul className="minions-rows">
              {rows.map((t) => {
                const next = NEXT[String(t.status)] ?? NEXT.todo;
                return (
                  <li
                    key={t.id}
                    className={`minions-row${t.status === "done" ? " done" : ""}`}
                  >
                    <div className="minions-row-main">
                      <span className="minions-row-title">
                        {String(t.title)}
                      </span>
                      <span className="field-label">
                        {t.status === "in_progress" ? "Started" : null}
                        {t.status === "in_progress" && t.due_at
                          ? ", due "
                          : t.due_at
                            ? "Due "
                            : null}
                        {t.due_at
                          ? new Date(String(t.due_at)).toLocaleDateString(
                              undefined,
                              { day: "numeric", month: "short" },
                            )
                          : null}
                        {t.priority === "high" || t.priority === "urgent" ? (
                          <span className="minions-flag">
                            {" "}
                            {String(t.priority)} priority
                          </span>
                        ) : null}
                      </span>
                    </div>
                    <button
                      type="button"
                      className={`minions-step${next.status === "done" ? " primary" : ""}`}
                      disabled={busy === t.id}
                      onClick={() => advance(t)}
                      aria-label={`${next.label}: ${String(t.title)}`}
                    >
                      {next.label}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
