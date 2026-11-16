-- Units on sale lines (owner, 2026-11-16): the unit a line was sold in
-- and how many of the product's base units one of it holds, copied at
-- sale time. Inventory takes quantity x uom_factor off stock, and a
-- return puts the same back.
ALTER TABLE invoice_lines ADD COLUMN uom_name TEXT NOT NULL DEFAULT '';
ALTER TABLE invoice_lines ADD COLUMN uom_factor NUMERIC(14, 6);
-- eTIMS: when the sold unit has no KRA code (a carton), the line is
-- reported in the base unit; quantity x etims_qty_factor.
ALTER TABLE invoice_lines ADD COLUMN etims_qty_factor NUMERIC(14, 6) NOT NULL DEFAULT 1;
