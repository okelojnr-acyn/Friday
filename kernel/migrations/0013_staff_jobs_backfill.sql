-- Plan section 12, step 2 (2026-11-22): the apps now check jobs. Staff who
-- joined before jobs existed keep what they could already do (sell, handle
-- stock, customers, deliveries); owners narrow it per person in People.
UPDATE core.memberships SET perms = ARRAY['cashier', 'warehouse', 'sales', 'logistics']
WHERE role = 'member' AND perms = '{}';
