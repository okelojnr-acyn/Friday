-- Online shop orders paid through the business's Paystack (Friday Host
-- STOREFRONT-PLAN.md, Commerce slice 3): their own source, so till and
-- shift reports (source 'pos') leave them out. source_ref is the order id.
ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_source_check;
ALTER TABLE invoices ADD CONSTRAINT invoices_source_check
    CHECK (source IN ('manual', 'crm', 'pos', 'credit_note', 'quote', 'shop'));
