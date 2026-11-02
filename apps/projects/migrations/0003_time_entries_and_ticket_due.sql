ALTER TABLE tickets ADD COLUMN due_at TIMESTAMPTZ;

CREATE TABLE time_entries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL,
    task_id     UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    minutes     INTEGER NOT NULL CHECK (minutes > 0),
    note        TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_time_entries_org ON time_entries(org_id);
CREATE INDEX idx_time_entries_task ON time_entries(task_id);

-- Row-Level Security: see apps/crm/migrations for the full explanation.
ALTER TABLE time_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE time_entries FORCE ROW LEVEL SECURITY;
CREATE POLICY time_entries_org_isolation ON time_entries
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
