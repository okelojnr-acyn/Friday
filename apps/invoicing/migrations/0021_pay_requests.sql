-- Pay requests: a sent invoice asks the business's payment provider to
-- request the money (Paystack Payment Request, Stripe Invoice, Pesapal
-- order); Friday checks the provider until it's paid. The open one only.
ALTER TABLE invoices
    ADD COLUMN IF NOT EXISTS pay_request_provider TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS pay_request_ref TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS pay_request_url TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS pay_request_cents BIGINT NOT NULL DEFAULT 0;
