import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import { ApiError } from "../lib/api";
import { listRecords, updateRecord } from "../lib/resourceApi";
import type { RecordRow } from "../lib/types";
import { Card } from "../ui/Card";
import { Badge, statusTone } from "../ui/Badge";
import { Select } from "../ui/Field";

const STATUSES = ["todo", "in_progress", "done"];

/** Minions' "My Tasks" doesn't duplicate Projects' Task resource -- it
 * calls GET/PATCH /api/projects/tasks directly, the same "web shell reads
 * multiple apps' APIs client-side" pattern the admin dashboard's stat
 * cards already use. assignee_email is free text today (see
 * apps/projects/app/models.py), so "my tasks" is a client-side string
 * match against the logged-in principal's email -- a real employee<->task
 * link is a documented follow-on, not in this pass. */
export function MyTasksPage() {
  const { session } = useAuth();
  const [tasks, setTasks] = useState<RecordRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listRecords("projects", "task")
      .then(setTasks)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load tasks"));
  }, []);

  async function setStatus(task: RecordRow, status: string) {
    try {
      const updated = await updateRecord("projects", "task", task.id, { status });
      setTasks((cur) => (cur ?? []).map((t) => (t.id === task.id ? updated : t)));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update task");
    }
  }

  if (error) return <div className="page error-banner">{error}</div>;
  if (!tasks) return <div className="page spinner">Loading...</div>;

  const mine = tasks.filter((t) => String(t.assignee_email ?? "").toLowerCase() === session?.email.toLowerCase());

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">My Tasks</h1>
      </div>

      {mine.length === 0 ? (
        <div className="empty-state">No tasks assigned to you yet.</div>
      ) : (
        mine.map((task) => (
          <Card key={task.id} style={{ marginBottom: 10 }}>
            <div className="pos-totals-row">
              <span>
                <strong>{String(task.title)}</strong>
                {task.due_at ? (
                  <span className="field-label" style={{ marginLeft: 8 }}>
                    Due {new Date(String(task.due_at)).toLocaleDateString()}
                  </span>
                ) : null}
              </span>
              <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <Badge tone={statusTone(String(task.priority))}>{String(task.priority)}</Badge>
                <Select value={String(task.status)} onChange={(e) => setStatus(task, e.target.value)}>
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </Select>
              </span>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
