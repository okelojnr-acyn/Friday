-- Paystack inside Friday (plan 15.3). The latest checkout's reference on
-- an invoice, so the till can verify it with Paystack without waiting
-- for the webhook; and the payment methods each till offers (NULL
-- follows the business's own list in the kernel's org settings).
ALTER TABLE invoices ADD COLUMN paystack_reference TEXT NOT NULL DEFAULT '';
ALTER TABLE pos_registers ADD COLUMN payment_methods TEXT[];
