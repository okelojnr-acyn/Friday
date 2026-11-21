-- Locations (plan section 12, step 2): the store or warehouse site a
-- warehouse belongs to (kernel core.locations id); NULL = not set.
-- shortcut: stock is still one count per product for the whole business
-- (moves are tagged by warehouse); per-location counts are a later step.
ALTER TABLE warehouses ADD COLUMN location_id UUID;
