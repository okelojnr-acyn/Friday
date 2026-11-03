-- Per-line tax rate (replaces the synthetic "Tax" invoice-line hack in
-- record_pos_sale -- see main.py) and per-customer payment terms, so
-- due_at can actually be set from something instead of staying null
-- forever. Also widens invoices.source for credit notes, which reuse the
-- same negated-lines pattern return_pos_sale already established for POS
-- refunds, applied to manual invoices.
ALTER TABLE invoice_lines ADD COLUMN tax_rate_bp INTEGER NOT NULL DEFAULT 0;

ALTER TABLE customers ADD COLUMN payment_terms_days INTEGER NOT NULL DEFAULT 30;

ALTER TABLE invoices DROP CONSTRAINT invoices_source_check;
ALTER TABLE invoices ADD CONSTRAINT invoices_source_check
    CHECK (source IN ('manual', 'crm', 'pos', 'credit_note'));
