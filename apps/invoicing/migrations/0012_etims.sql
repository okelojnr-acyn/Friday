-- KRA eTIMS (owner, 2026-11-16). For now sales are filed by hand in
-- KRA's eTIMS portal and the invoice number KRA gives is recorded here;
-- the automated sender (OSCU) fills the same columns once a server is
-- allowed to (ETIMS_AUTOMATION=1, production checks).

-- The buyer's KRA PIN: a business buying needs it on the eTIMS invoice
-- to claim the VAT and the expense.
ALTER TABLE invoices ADD COLUMN buyer_pin TEXT NOT NULL DEFAULT '';
ALTER TABLE invoices ADD COLUMN buyer_name TEXT NOT NULL DEFAULT '';
-- How the till priced the sale (VAT inside the price or added).
ALTER TABLE invoices ADD COLUMN prices_include_tax BOOLEAN;
ALTER TABLE invoices ADD COLUMN etims_status TEXT NOT NULL DEFAULT 'unfiled'
    CHECK (etims_status IN ('unfiled', 'submitted', 'failed'));
ALTER TABLE invoices ADD COLUMN etims_via TEXT NOT NULL DEFAULT ''
    CHECK (etims_via IN ('', 'manual', 'oscu', 'vscu'));
-- The number KRA's eTIMS shows for the invoice (the portal's invoice
-- number, or the control unit's receipt number when sent by OSCU).
ALTER TABLE invoices ADD COLUMN etims_invoice_no TEXT NOT NULL DEFAULT '';
-- Friday's eTIMS invoice number (invcNo): one sequence per organisation.
ALTER TABLE invoices ADD COLUMN etims_trader_no BIGINT;
ALTER TABLE invoices ADD COLUMN etims_receipt_sign TEXT NOT NULL DEFAULT '';
ALTER TABLE invoices ADD COLUMN etims_internal_data TEXT NOT NULL DEFAULT '';
ALTER TABLE invoices ADD COLUMN etims_sdc_time TEXT NOT NULL DEFAULT '';
ALTER TABLE invoices ADD COLUMN etims_filed_at TIMESTAMPTZ;
ALTER TABLE invoices ADD COLUMN etims_filed_by TEXT NOT NULL DEFAULT '';
ALTER TABLE invoices ADD COLUMN etims_error TEXT NOT NULL DEFAULT '';
ALTER TABLE invoices ADD COLUMN etims_attempts INTEGER NOT NULL DEFAULT 0;
CREATE INDEX idx_invoices_etims ON invoices (org_id, etims_status, issued_at);
CREATE UNIQUE INDEX invoices_etims_trader_no ON invoices (org_id, etims_trader_no) WHERE etims_trader_no IS NOT NULL;

-- Each line's tax type (eTIMS A-E) and the VAT in or on it.
ALTER TABLE invoice_lines ADD COLUMN tax_code TEXT NOT NULL DEFAULT '';
ALTER TABLE invoice_lines ADD COLUMN vat_cents BIGINT NOT NULL DEFAULT 0;
-- The till's "Tax"/"Discount" reconciling line is not an item.
ALTER TABLE invoice_lines ADD COLUMN is_adjustment BOOLEAN NOT NULL DEFAULT false;
-- The backfill must see every org's lines.
ALTER TABLE invoice_lines NO FORCE ROW LEVEL SECURITY;
UPDATE invoice_lines SET is_adjustment = true
    WHERE product_id IS NULL AND description IN ('Tax', 'Discount') AND quantity = 1;
ALTER TABLE invoice_lines FORCE ROW LEVEL SECURITY;
-- What eTIMS needs to know about the item, copied at sale time.
ALTER TABLE invoice_lines ADD COLUMN item_code TEXT NOT NULL DEFAULT '';
ALTER TABLE invoice_lines ADD COLUMN item_class TEXT NOT NULL DEFAULT '';
ALTER TABLE invoice_lines ADD COLUMN quantity_unit TEXT NOT NULL DEFAULT '';
ALTER TABLE invoice_lines ADD COLUMN packaging_unit TEXT NOT NULL DEFAULT '';
-- Grams and millilitres: three decimals.
ALTER TABLE invoice_lines ALTER COLUMN quantity TYPE NUMERIC(14, 3);

CREATE TABLE etims_sequences (
    org_id  UUID PRIMARY KEY,
    last_no BIGINT NOT NULL DEFAULT 0
);
ALTER TABLE etims_sequences ENABLE ROW LEVEL SECURITY;
ALTER TABLE etims_sequences FORCE ROW LEVEL SECURITY;
CREATE POLICY etims_sequences_org_isolation ON etims_sequences
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
