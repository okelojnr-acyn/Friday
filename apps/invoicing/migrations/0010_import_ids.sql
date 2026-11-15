-- Imported customers remember where they came from (plan 2.4): the
-- source's name and its own id. Re-running an import updates the same
-- rows; customers made in Friday have NULLs and never collide.
ALTER TABLE customers ADD COLUMN external_source TEXT;
ALTER TABLE customers ADD COLUMN external_id TEXT;
CREATE UNIQUE INDEX customers_external ON customers (org_id, external_source, external_id);
