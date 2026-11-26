-- Spending plan part C (Friday Host docs/SPENDING-PLAN.md): petty cash
-- (imprest). A float per location with one holder; every movement is a
-- row (a top-up in, a slip out, a count's over or short), so the cash the
-- holder should have is their sum. A petty cash claim is the slip: the
-- holder confirms it came out of the box.
CREATE TABLE petty_floats (
    id             UUID PRIMARY KEY,
    org_id         UUID NOT NULL,
    name           TEXT NOT NULL,
    location_id    TEXT NOT NULL DEFAULT '',
    holder_user_id TEXT NOT NULL,
    holder_name    TEXT NOT NULL DEFAULT '',
    float_cents    BIGINT NOT NULL CHECK (float_cents > 0),
    currency       TEXT NOT NULL DEFAULT 'KES',
    active         BOOLEAN NOT NULL DEFAULT true,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX uq_petty_floats_location ON petty_floats (org_id, location_id) WHERE active;

CREATE TABLE petty_moves (
    id           UUID PRIMARY KEY,
    org_id       UUID NOT NULL,
    float_id     UUID NOT NULL REFERENCES petty_floats(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL CHECK (kind IN ('top_up', 'slip', 'count')),
    amount_cents BIGINT NOT NULL,  -- signed: in > 0, out < 0
    claim_id     UUID,
    method       TEXT NOT NULL DEFAULT '',
    reference    TEXT NOT NULL DEFAULT '',
    note         TEXT NOT NULL DEFAULT '',
    by_name      TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_petty_moves_float ON petty_moves (float_id, created_at);

ALTER TABLE petty_floats ENABLE ROW LEVEL SECURITY;
ALTER TABLE petty_floats FORCE ROW LEVEL SECURITY;
CREATE POLICY petty_floats_org_isolation ON petty_floats
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
ALTER TABLE petty_moves ENABLE ROW LEVEL SECURITY;
ALTER TABLE petty_moves FORCE ROW LEVEL SECURITY;
CREATE POLICY petty_moves_org_isolation ON petty_moves
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

-- Which float a petty cash claim came out of.
ALTER TABLE expense_claims ADD COLUMN IF NOT EXISTS float_id UUID REFERENCES petty_floats(id) ON DELETE SET NULL;
