-- Quotes (P1 quote-to-cash, 2026-11-10). A quote is the same document
-- shape as an invoice -- customer, currency, lines with tax/discount --
-- so it lives in the same table, distinguished by `kind`, rather than a
-- parallel quotes/quote_lines pair that would duplicate every line rule
-- (tax, discount, totals) and drift. Everything money-facing (payments,
-- AR aging, overdue, list_invoices) filters to kind = 'invoice'.
ALTER TABLE invoices ADD COLUMN kind TEXT NOT NULL DEFAULT 'invoice'
    CHECK (kind IN ('invoice', 'quote'));
ALTER TABLE invoices ADD COLUMN valid_until TIMESTAMPTZ;

-- Quote lifecycle: draft -> sent -> accepted (converted to an invoice) |
-- declined. Same drop+add pattern as 0007_pos_identity.sql.
ALTER TABLE invoices DROP CONSTRAINT invoices_status_check;
ALTER TABLE invoices ADD CONSTRAINT invoices_status_check
    CHECK (status IN ('draft', 'sent', 'paid', 'void', 'pending', 'accepted', 'declined'));

-- An invoice converted from a quote records source = 'quote' and
-- source_ref = the quote's id.
ALTER TABLE invoices DROP CONSTRAINT invoices_source_check;
ALTER TABLE invoices ADD CONSTRAINT invoices_source_check
    CHECK (source IN ('manual', 'crm', 'pos', 'credit_note', 'quote'));

CREATE INDEX idx_invoices_kind_status ON invoices(org_id, kind, status);
