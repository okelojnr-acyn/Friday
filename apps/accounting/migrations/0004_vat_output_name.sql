-- 2200 was seeded as "Tax Payable" before 2026-11-16; it holds VAT charged
-- on sales, so it is now "VAT Output (payable)". Seeding never renames an
-- existing account, so orgs seeded earlier are renamed here. An account
-- the business renamed itself is left alone.
-- The rename must see every org's rows; RLS is forced again below.
ALTER TABLE accounts NO FORCE ROW LEVEL SECURITY;
UPDATE accounts SET name = 'VAT Output (payable)' WHERE code = '2200' AND name = 'Tax Payable';
ALTER TABLE accounts FORCE ROW LEVEL SECURITY;
