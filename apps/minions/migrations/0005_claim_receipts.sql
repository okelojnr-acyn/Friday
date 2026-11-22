-- Receipt photos on expense claims (plan 12.3: "submit expense with
-- photo"). Kept in the database like product photos, so they're backed up
-- with everything else; receipt_sha changes when the photo does.
CREATE TABLE claim_receipts (
    claim_id     UUID PRIMARY KEY REFERENCES expense_claims(id) ON DELETE CASCADE,
    org_id       UUID NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('image/webp', 'image/jpeg', 'image/png')),
    data         BYTEA NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE claim_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_receipts FORCE ROW LEVEL SECURITY;
CREATE POLICY claim_receipts_org_isolation ON claim_receipts
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

ALTER TABLE expense_claims ADD COLUMN receipt_sha TEXT NOT NULL DEFAULT '';
