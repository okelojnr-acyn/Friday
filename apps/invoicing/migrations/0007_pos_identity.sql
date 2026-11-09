-- Cashier/employee identity on POS sales and shifts -- neither carried
-- any identity before this, even though the authenticated caller
-- (Principal.user_id/email) was always available. Stamped directly on
-- the sale rather than derived from the open shift, so it's correct
-- even in the documented "one open shift per org" gap case.
ALTER TABLE invoices
    ADD COLUMN cashier_user_id TEXT,
    ADD COLUMN cashier_email TEXT;

ALTER TABLE pos_shifts
    ADD COLUMN opened_by_user_id TEXT,
    ADD COLUMN opened_by_email TEXT;

-- "pending": a POS sale submitted to a real payment gateway (Pesapal)
-- but not yet confirmed -- cash/card-today never needed this state
-- since they're recorded already-paid. See
-- apps/invoicing/app/main.py's pay_with_pesapal/pesapal_webhook.
ALTER TABLE invoices DROP CONSTRAINT invoices_status_check;
ALTER TABLE invoices ADD CONSTRAINT invoices_status_check
    CHECK (status IN ('draft', 'sent', 'paid', 'void', 'pending'));
