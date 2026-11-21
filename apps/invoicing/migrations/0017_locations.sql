-- Locations (plan section 12, step 2): which store or warehouse a till
-- stands in, and so where each sale was made. Kernel core.locations ids;
-- NULL = not set (a Guss sale, an invoice, a till nobody placed yet).
ALTER TABLE pos_registers ADD COLUMN location_id UUID;
ALTER TABLE invoices ADD COLUMN location_id UUID;
CREATE INDEX idx_invoices_location ON invoices (org_id, location_id) WHERE location_id IS NOT NULL;
