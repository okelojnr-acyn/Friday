-- Organisation settings every app reads (owner, 2026-11-15): money was
-- shown in dollars everywhere and the POS charged a flat 8% "USD" tax.
-- Defaults suit the shops Friday is built for (Kenya: KSh, 16% VAT,
-- shelf prices that already include VAT); owners change them in Friday.
ALTER TABLE core.orgs ADD COLUMN currency TEXT NOT NULL DEFAULT 'KES'
    CHECK (currency ~ '^[A-Z]{3}$');
ALTER TABLE core.orgs ADD COLUMN tax_rate_bp INTEGER NOT NULL DEFAULT 1600
    CHECK (tax_rate_bp BETWEEN 0 AND 5000);
ALTER TABLE core.orgs ADD COLUMN prices_include_tax BOOLEAN NOT NULL DEFAULT true;
