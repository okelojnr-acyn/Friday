-- Cheap equivalent of Odoo's reordering rules: a visible threshold next
-- to on_hand_qty, not a replenishment engine with purchase orders.
ALTER TABLE products ADD COLUMN reorder_point INTEGER NOT NULL DEFAULT 0;
