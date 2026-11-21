-- Where a sale was made (owner, 2026-11-21): at a till, or through Guss
-- (the shop assistant on WhatsApp/Telegram). Guss records its sales here
-- so stock, VAT, the books, eTIMS and the VAT return all come from one
-- record. A Guss sale never joins a till's shift: its cash isn't in that
-- drawer.
ALTER TABLE invoices ADD COLUMN channel TEXT NOT NULL DEFAULT 'till';
CREATE INDEX idx_invoices_pos_day ON invoices (org_id, issued_at) WHERE source = 'pos';
