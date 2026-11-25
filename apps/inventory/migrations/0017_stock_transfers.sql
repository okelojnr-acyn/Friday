-- Moving stock between stores (HR plan 8.2, warehouse work): one
-- transfer is two moves (out of one warehouse, into another) written
-- together; the total on hand doesn't change.
ALTER TABLE stock_moves DROP CONSTRAINT IF EXISTS stock_moves_reason_check;
ALTER TABLE stock_moves ADD CONSTRAINT stock_moves_reason_check
    CHECK (reason IN ('manual_adjustment', 'pos_sale', 'received', 'sale', 'write_off', 'transfer'));
