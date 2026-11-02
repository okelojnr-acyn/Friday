CREATE TABLE opportunities (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL,
    contact_name  TEXT NOT NULL,
    contact_email TEXT NOT NULL DEFAULT '',
    company       TEXT NOT NULL DEFAULT '',
    stage         TEXT NOT NULL DEFAULT 'new'
                  CHECK (stage IN ('new', 'qualified', 'proposition', 'won', 'lost')),
    value_cents   BIGINT NOT NULL DEFAULT 0,
    currency      TEXT NOT NULL DEFAULT 'USD',
    notes         TEXT NOT NULL DEFAULT '',
    created_by    UUID,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_opportunities_org ON opportunities(org_id);
CREATE INDEX idx_opportunities_stage ON opportunities(org_id, stage);

-- Row-Level Security: the org boundary is enforced in Postgres itself, not
-- only by an application-layer WHERE clause. friday_common.get_org_session
-- sets app.current_org_id via SET LOCAL at the start of every request.
ALTER TABLE opportunities ENABLE ROW LEVEL SECURITY;
-- FORCE so the policy applies even to the table owner -- in this starter
-- setup the app connects with the same role that ran the migrations. In a
-- hardened deployment, run migrations as an admin role and connect the app
-- as a separate, non-owner role instead (FORCE becomes unnecessary then).
ALTER TABLE opportunities FORCE ROW LEVEL SECURITY;

CREATE POLICY opportunities_org_isolation ON opportunities
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
