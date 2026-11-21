-- Purchases for the VAT return (owner, 2026-11-16). A supplier's KRA
-- PIN, the supplier's own invoice number and date, and each line's tax
-- type and VAT: what iTax's purchases schedule (VAT3 Section F) asks
-- for, and what Accounting books as input VAT when goods are received.
-- Line costs are before VAT.
ALTER TABLE suppliers ADD COLUMN kra_pin TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_orders ADD COLUMN supplier_invoice_no TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_orders ADD COLUMN supplier_invoice_date DATE;
ALTER TABLE purchase_orders ADD COLUMN received_at TIMESTAMPTZ;
ALTER TABLE purchase_order_lines ADD COLUMN tax_code TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_order_lines ADD COLUMN vat_cents BIGINT NOT NULL DEFAULT 0;
