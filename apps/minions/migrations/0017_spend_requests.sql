-- Spending plan part B (Friday Host docs/SPENDING-PLAN.md): asking first.
-- A spend request (or a trip: where, when, an optional cash advance) is
-- routed up the reporting line like a claim. The later claims carry it;
-- a trip's advance is settled against its claims, the rest given back or
-- taken off pay.
CREATE TABLE spend_requests (
    id                 UUID PRIMARY KEY,
    org_id             UUID NOT NULL,
    employee_id        UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    kind               TEXT NOT NULL DEFAULT 'spend' CHECK (kind IN ('spend', 'trip')),
    description        TEXT NOT NULL,
    amount_cents       BIGINT NOT NULL CHECK (amount_cents > 0),
    currency           TEXT NOT NULL DEFAULT 'KES',
    for_kind           TEXT NOT NULL DEFAULT 'daily',
    for_id             TEXT NOT NULL DEFAULT '',
    for_label          TEXT NOT NULL DEFAULT '',
    category           TEXT NOT NULL DEFAULT 'other',
    destination        TEXT NOT NULL DEFAULT '',
    starts_on          DATE,
    ends_on            DATE,
    advance_cents      BIGINT NOT NULL DEFAULT 0 CHECK (advance_cents >= 0),
    status             TEXT NOT NULL DEFAULT 'submitted'
                       CHECK (status IN ('submitted', 'approved', 'rejected', 'withdrawn', 'closed')),
    waiting_on_user_id TEXT NOT NULL DEFAULT '',
    waiting_on_name    TEXT NOT NULL DEFAULT '',
    decision_note      TEXT NOT NULL DEFAULT '',
    decided_by_name    TEXT NOT NULL DEFAULT '',
    decided_at         TIMESTAMPTZ,
    advance_method     TEXT NOT NULL DEFAULT '',
    advance_reference  TEXT NOT NULL DEFAULT '',
    advance_paid_at    TIMESTAMPTZ,
    spent_cents        BIGINT NOT NULL DEFAULT 0,
    settle_method      TEXT NOT NULL DEFAULT '',
    closed_at          TIMESTAMPTZ,
    submitted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_spend_requests_person ON spend_requests (org_id, employee_id);
CREATE INDEX idx_spend_requests_waiting ON spend_requests (org_id, waiting_on_user_id) WHERE status = 'submitted';
ALTER TABLE spend_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE spend_requests FORCE ROW LEVEL SECURITY;
CREATE POLICY spend_requests_org_isolation ON spend_requests
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

-- A claim carries the request it was asked under, or says it wasn't
-- asked first (an emergency, with a reason); a claim over its approval by
-- more than the policy's tolerance is flagged.
ALTER TABLE expense_claims
    ADD COLUMN IF NOT EXISTS request_id UUID REFERENCES spend_requests(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS emergency_reason TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS flag TEXT NOT NULL DEFAULT '';
