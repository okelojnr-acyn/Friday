-- Shelf grouping for the till's category buttons (owner, 2026-11-15).
ALTER TABLE products ADD COLUMN category TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_products_org_category ON products (org_id, category) WHERE category <> '';
