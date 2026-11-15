-- A sale's stock comes off once (owner's busy-evening question,
-- 2026-11-16). The POS-sale webhook now records one stock move per sale
-- and product before touching on_hand_qty, so a repeated delivery of the
-- same sale changes nothing, and the decrement itself is one atomic
-- UPDATE (two tills selling the same item at once both count).

-- Earlier repeats (possible before this) keep their rows but get a
-- distinct reference so the rule can hold from now on.
ALTER TABLE stock_moves NO FORCE ROW LEVEL SECURITY;
UPDATE stock_moves m SET reference = m.reference || ':dup:' || m.id
WHERE m.reason = 'pos_sale' AND m.reference <> ''
  AND EXISTS (
    SELECT 1 FROM stock_moves o
    WHERE o.org_id = m.org_id AND o.product_id = m.product_id AND o.reason = 'pos_sale'
      AND o.reference = m.reference AND (o.created_at, o.id) < (m.created_at, m.id));
ALTER TABLE stock_moves FORCE ROW LEVEL SECURITY;

CREATE UNIQUE INDEX stock_moves_pos_sale_once ON stock_moves (org_id, product_id, reference)
    WHERE reason = 'pos_sale' AND reference <> '';
