-- KRA eTIMS on each product (owner, 2026-11-16): its tax type (A-E;
-- '' = the business's default rate), KRA's item classification (UNSPSC)
-- and packaging unit, and the item code eTIMS knows it by once Friday
-- registers it (/saveItem, automated sending only).
ALTER TABLE products ADD COLUMN tax_code TEXT NOT NULL DEFAULT ''
    CHECK (tax_code IN ('', 'A', 'B', 'C', 'D', 'E'));
ALTER TABLE products ADD COLUMN etims_item_class TEXT NOT NULL DEFAULT '';
ALTER TABLE products ADD COLUMN etims_packaging_unit TEXT NOT NULL DEFAULT 'NT';
ALTER TABLE products ADD COLUMN etims_item_code TEXT NOT NULL DEFAULT '';
ALTER TABLE products ADD COLUMN etims_registered_at TIMESTAMPTZ;

CREATE TABLE etims_item_sequences (
    org_id  UUID PRIMARY KEY,
    last_no BIGINT NOT NULL DEFAULT 0
);
ALTER TABLE etims_item_sequences ENABLE ROW LEVEL SECURITY;
ALTER TABLE etims_item_sequences FORCE ROW LEVEL SECURITY;
CREATE POLICY etims_item_sequences_org_isolation ON etims_item_sequences
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
