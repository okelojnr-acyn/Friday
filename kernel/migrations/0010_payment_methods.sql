-- Payment methods a business offers (plan 15.3): cash, M-Pesa, card,
-- Paystack, Pesapal. NULL means all of them; a till can narrow its own
-- list (invoicing's pos_registers.payment_methods).
ALTER TABLE core.orgs ADD COLUMN payment_methods TEXT[];
