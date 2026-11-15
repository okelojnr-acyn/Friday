-- Stock changes recorded by Guss (the shop assistant) say what they are:
-- a sale told to Guss is "sale", stock that spoiled or was lost is
-- "write_off". Guss also tags every move with reference "guss:<entry id>"
-- (and "guss-void:<entry id>" when it is reversed), which is how it
-- avoids recording the same entry twice.
ALTER TABLE stock_moves DROP CONSTRAINT IF EXISTS stock_moves_reason_check;
ALTER TABLE stock_moves ADD CONSTRAINT stock_moves_reason_check
    CHECK (reason IN ('manual_adjustment', 'pos_sale', 'received', 'sale', 'write_off'));
CREATE INDEX IF NOT EXISTS idx_stock_moves_reference ON stock_moves (org_id, reference);
