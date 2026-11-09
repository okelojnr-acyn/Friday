-- Links Projects into the rest of Friday instead of sitting as an
-- island: a won CRM deal can become a project, and a helpdesk ticket
-- can be tied to the real paying customer who raised it. By-id-only,
-- no FK across schemas -- same convention as minions.employees.user_id
-- (see that table's own comment).
ALTER TABLE projects ADD COLUMN opportunity_id UUID;
ALTER TABLE tickets ADD COLUMN customer_id UUID;
