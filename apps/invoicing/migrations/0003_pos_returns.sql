-- Lets an invoice line remember which product it came from (POS sales
-- already threaded product_id through the event payload, but never
-- persisted it) -- the POS return flow needs this to restock the right
-- product when refunding a past sale. Plain UUID, no FK: invoicing never
-- takes a cross-schema/cross-app foreign key on inventory's product id,
-- same rule as everywhere else in this codebase (see ARCHITECTURE.md's
-- "Data ownership").
ALTER TABLE invoice_lines ADD COLUMN product_id UUID;

ALTER TABLE payments DROP CONSTRAINT payments_method_check;
ALTER TABLE payments ADD CONSTRAINT payments_method_check
    CHECK (method IN ('cash', 'card', 'pos', 'bank_transfer', 'refund', 'other'));
