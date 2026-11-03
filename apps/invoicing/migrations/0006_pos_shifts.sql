CREATE TABLE pos_shifts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL,
    opened_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at           TIMESTAMPTZ,
    opening_float_cents BIGINT NOT NULL DEFAULT 0,
    closing_count_cents BIGINT,
    expected_cents      BIGINT,
    status              TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed'))
);
CREATE INDEX idx_pos_shifts_org ON pos_shifts(org_id);
-- Enforces "one open shift per org at a time" at the database level,
-- not just in application code -- a partial unique index on status
-- rather than a CHECK, since CHECK can't reference other rows.
CREATE UNIQUE INDEX idx_pos_shifts_one_open_per_org ON pos_shifts(org_id) WHERE status = 'open';
ALTER TABLE pos_shifts ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_shifts FORCE ROW LEVEL SECURITY;
CREATE POLICY pos_shifts_org_isolation ON pos_shifts
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
