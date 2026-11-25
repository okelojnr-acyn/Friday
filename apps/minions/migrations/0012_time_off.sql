-- Time off (HR plan phase 3): asked for, decided up the reporting line
-- like a claim, shown on calendars. Annual leave counts against 21 working
-- days a year (owner default); sick and unpaid are recorded.
CREATE TABLE time_off (
    id                 UUID PRIMARY KEY,
    org_id             UUID NOT NULL,
    employee_id        UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    kind               TEXT NOT NULL CHECK (kind IN ('annual', 'sick', 'unpaid')),
    starts_on          DATE NOT NULL,
    ends_on            DATE NOT NULL,
    days               INT NOT NULL CHECK (days > 0),
    note               TEXT NOT NULL DEFAULT '',
    description        TEXT NOT NULL DEFAULT '',
    status             TEXT NOT NULL DEFAULT 'submitted'
                       CHECK (status IN ('submitted', 'approved', 'rejected', 'withdrawn')),
    waiting_on_user_id TEXT NOT NULL DEFAULT '',
    waiting_on_name    TEXT NOT NULL DEFAULT '',
    decision_note      TEXT NOT NULL DEFAULT '',
    decided_by_name    TEXT NOT NULL DEFAULT '',
    decided_at         TIMESTAMPTZ,
    submitted_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (ends_on >= starts_on)
);
CREATE INDEX idx_time_off_person ON time_off (org_id, employee_id, starts_on);
ALTER TABLE time_off ENABLE ROW LEVEL SECURITY;
ALTER TABLE time_off FORCE ROW LEVEL SECURITY;
CREATE POLICY time_off_org_isolation ON time_off
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
