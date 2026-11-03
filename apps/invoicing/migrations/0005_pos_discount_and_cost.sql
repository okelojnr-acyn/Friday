-- Real per-line discount (basis points, mirroring pos-engine's
-- LineItem.discount_bp) replacing the old client-side approach of baking
-- a discount directly into unit_price_cents, plus a cost basis so
-- Accounting's (planned) COGS webhook has something to post against
-- without ever querying Inventory directly.
ALTER TABLE invoice_lines ADD COLUMN discount_bp INTEGER NOT NULL DEFAULT 0;
ALTER TABLE invoice_lines ADD COLUMN unit_cost_cents BIGINT;
