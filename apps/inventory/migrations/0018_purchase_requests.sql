-- Spending plan part D: a request to buy comes before the order. A draft
-- is sent for approval (requested), someone else approves it (approved)
-- or sends it back with a reason (draft again), then it's ordered.
-- Ordering a draft straight away stays open up to the person's ask-first
-- amount (Business settings > Spending); owners and admins always.
ALTER TABLE purchase_orders DROP CONSTRAINT IF EXISTS purchase_orders_status_check;
ALTER TABLE purchase_orders ADD CONSTRAINT purchase_orders_status_check
    CHECK (status IN ('draft', 'requested', 'approved', 'ordered', 'received'));
ALTER TABLE purchase_orders
    ADD COLUMN IF NOT EXISTS requested_by_user_id TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS requested_by_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS decided_by_name TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS decision_note TEXT NOT NULL DEFAULT '';
