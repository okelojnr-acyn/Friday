-- Tasks down the reporting line (HR plan 8.4.2): a task belongs to a
-- person (their Friday user id, not a typed email), remembers who gave
-- it, and how far its overdue notice has gone (0 none, 1 the due day:
-- assignee and assigner, 2 three days later: the next person up).
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignee_user_id TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assignee_name TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_by_user_id TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS assigned_by_name TEXT NOT NULL DEFAULT '';
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS overdue_level SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS done_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks (org_id, assignee_user_id);
CREATE INDEX IF NOT EXISTS idx_tasks_overdue ON tasks (org_id, due_at) WHERE status <> 'done';
