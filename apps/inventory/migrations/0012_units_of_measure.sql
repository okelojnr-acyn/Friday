-- Units of measure that hold up for accuracy and restocking (owner,
-- 2026-11-16). Every product keeps stock in one base unit, is bought in
-- a purchase unit and sold in a sales unit, each with how many base
-- units it holds. Stock and quantities take three decimals (grams,
-- millilitres); before this a 0.5 kg sale was rounded to a whole unit
-- and receiving a carton added 1.
--
-- Units: a standard set is preloaded per organisation (seeded by the
-- app on first use, app/uom.py) and can be benched (hidden from pickers)
-- when a business doesn't use it. A unit with a ratio converts within
-- its category (1 kg = 1000 g); a pack (carton, crate, ...) has no ratio:
-- its size is set per product (a carton of 24, a carton of 12).

ALTER TABLE units_of_measure ADD COLUMN code TEXT NOT NULL DEFAULT '';
ALTER TABLE units_of_measure ADD COLUMN category TEXT NOT NULL DEFAULT 'unit'
    CHECK (category IN ('unit', 'weight', 'volume', 'length', 'area', 'time'));
ALTER TABLE units_of_measure ADD COLUMN ratio NUMERIC(20, 10);
ALTER TABLE units_of_measure ADD COLUMN etims_code TEXT NOT NULL DEFAULT '';
ALTER TABLE units_of_measure ADD COLUMN active BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE units_of_measure ADD COLUMN sort INTEGER NOT NULL DEFAULT 100;
CREATE UNIQUE INDEX units_of_measure_code ON units_of_measure (org_id, code) WHERE code <> '';

ALTER TABLE products ALTER COLUMN on_hand_qty TYPE NUMERIC(14, 3);
ALTER TABLE products ALTER COLUMN reorder_point TYPE NUMERIC(14, 3);
ALTER TABLE products ADD COLUMN base_uom_id UUID REFERENCES units_of_measure(id) ON DELETE SET NULL;
ALTER TABLE products ADD COLUMN purchase_uom_id UUID REFERENCES units_of_measure(id) ON DELETE SET NULL;
ALTER TABLE products ADD COLUMN purchase_factor NUMERIC(14, 6) NOT NULL DEFAULT 1 CHECK (purchase_factor > 0);
ALTER TABLE products ADD COLUMN sales_uom_id UUID REFERENCES units_of_measure(id) ON DELETE SET NULL;
ALTER TABLE products ADD COLUMN sales_factor NUMERIC(14, 6) NOT NULL DEFAULT 1 CHECK (sales_factor > 0);

-- The old single unit (uom_id, uom_conversion_factor) described the unit
-- a product was bought and sold by; it becomes the purchase unit.
ALTER TABLE products NO FORCE ROW LEVEL SECURITY;
UPDATE products SET purchase_uom_id = uom_id, purchase_factor = uom_conversion_factor
    WHERE uom_id IS NOT NULL AND uom_conversion_factor > 0;
ALTER TABLE products FORCE ROW LEVEL SECURITY;

ALTER TABLE stock_moves ALTER COLUMN qty_delta TYPE NUMERIC(14, 3);

-- A purchase order line is in the unit it was ordered in; receiving adds
-- quantity x uom_factor base units. Copied when the line is made, so a
-- later change to the product doesn't change an order already placed.
ALTER TABLE purchase_order_lines ALTER COLUMN quantity TYPE NUMERIC(14, 3);
ALTER TABLE purchase_order_lines ADD COLUMN uom_id UUID REFERENCES units_of_measure(id) ON DELETE SET NULL;
ALTER TABLE purchase_order_lines ADD COLUMN uom_name TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_order_lines ADD COLUMN uom_factor NUMERIC(14, 6) NOT NULL DEFAULT 1 CHECK (uom_factor > 0);
