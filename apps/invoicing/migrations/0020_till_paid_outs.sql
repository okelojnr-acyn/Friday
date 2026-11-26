-- Paying out of the till (spending plan part C): off by default (a separate
-- petty cash float is the standard); when the owner turns it on, each
-- payout is recorded on the open shift and comes off the cash expected.
CREATE TABLE pos_paid_outs (
    id           UUID PRIMARY KEY,
    org_id       UUID NOT NULL,
    shift_id     UUID NOT NULL REFERENCES pos_shifts(id) ON DELETE CASCADE,
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    description  TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'other',
    by_user_id   TEXT NOT NULL DEFAULT '',
    by_email     TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_pos_paid_outs_shift ON pos_paid_outs (shift_id);
ALTER TABLE pos_paid_outs ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_paid_outs FORCE ROW LEVEL SECURITY;
CREATE POLICY pos_paid_outs_org_isolation ON pos_paid_outs
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
