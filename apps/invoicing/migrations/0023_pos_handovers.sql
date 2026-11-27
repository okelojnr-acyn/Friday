-- Cashier handover with a drawer count (plan 20.3): when the cashier
-- changes mid-shift, the outgoing one counts the drawer. Each handover
-- keeps what was counted and what the drawer should have held then, so a
-- shortage is pinned on the stretch (and the cashier) it happened in.
CREATE TABLE pos_handovers (
    id             UUID PRIMARY KEY,
    org_id         UUID NOT NULL,
    shift_id       UUID NOT NULL REFERENCES pos_shifts(id) ON DELETE CASCADE,
    counted_cents  BIGINT NOT NULL CHECK (counted_cents >= 0),
    expected_cents BIGINT NOT NULL,
    by_user_id     TEXT NOT NULL DEFAULT '',
    by_email       TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_pos_handovers_shift ON pos_handovers (shift_id, created_at);
ALTER TABLE pos_handovers ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_handovers FORCE ROW LEVEL SECURITY;
CREATE POLICY pos_handovers_org_isolation ON pos_handovers
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
