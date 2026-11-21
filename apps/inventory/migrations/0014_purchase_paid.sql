-- Paying the supplier (2026-11-21). Receiving goods books what is owed
-- (Cr Accounts Payable); paying it books Dr Accounts Payable and Cr the
-- account the money left from. One payment per purchase order: the whole
-- amount owed, cost plus VAT.
ALTER TABLE purchase_orders ADD COLUMN paid_at TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN paid_method TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_orders ADD COLUMN paid_reference TEXT NOT NULL DEFAULT '';
