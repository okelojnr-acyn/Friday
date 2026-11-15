-- Imported products and suppliers remember where they came from (plan
-- 2.4); see apps/invoicing/migrations/0010_import_ids.sql.
ALTER TABLE products ADD COLUMN external_source TEXT;
ALTER TABLE products ADD COLUMN external_id TEXT;
CREATE UNIQUE INDEX products_external ON products (org_id, external_source, external_id);

ALTER TABLE suppliers ADD COLUMN external_source TEXT;
ALTER TABLE suppliers ADD COLUMN external_id TEXT;
CREATE UNIQUE INDEX suppliers_external ON suppliers (org_id, external_source, external_id);
