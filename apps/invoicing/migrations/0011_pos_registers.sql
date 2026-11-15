-- Registers (tills) and one shift per register (owner, 2026-11-15).
-- Before this there was one open shift per organisation, so a second
-- till, or a second store, couldn't open a shift at all, and the close
-- counted every cash payment in the org during the shift's hours.

CREATE TABLE pos_registers (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL,
    name          TEXT NOT NULL,
    -- The store or site it stands in (free text until locations land,
    -- plan section 12).
    location_name TEXT NOT NULL DEFAULT '',
    active        BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX pos_registers_name ON pos_registers (org_id, lower(name));

-- Every org that already used shifts gets a "Main till" holding them.
INSERT INTO pos_registers (org_id, name) SELECT DISTINCT org_id, 'Main till' FROM pos_shifts;

ALTER TABLE pos_registers ENABLE ROW LEVEL SECURITY;
ALTER TABLE pos_registers FORCE ROW LEVEL SECURITY;
CREATE POLICY pos_registers_org_isolation ON pos_registers
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

-- The backfills below must see every org's rows; RLS is forced again at
-- the end of this file.
ALTER TABLE pos_shifts NO FORCE ROW LEVEL SECURITY;
ALTER TABLE invoices NO FORCE ROW LEVEL SECURITY;
ALTER TABLE pos_registers NO FORCE ROW LEVEL SECURITY;

ALTER TABLE pos_shifts ADD COLUMN register_id UUID REFERENCES pos_registers(id);
ALTER TABLE pos_shifts ADD COLUMN closed_by_user_id TEXT;
ALTER TABLE pos_shifts ADD COLUMN closed_by_email TEXT;
ALTER TABLE pos_shifts ADD COLUMN close_note TEXT NOT NULL DEFAULT '';
-- What the close found: sales and refunds by method, counts.
ALTER TABLE pos_shifts ADD COLUMN summary JSONB;
UPDATE pos_shifts s SET register_id = r.id FROM pos_registers r
    WHERE r.org_id = s.org_id AND r.name = 'Main till' AND s.register_id IS NULL;

DROP INDEX idx_pos_shifts_one_open_per_org;
CREATE UNIQUE INDEX idx_pos_shifts_one_open_per_register ON pos_shifts (register_id) WHERE status = 'open';
CREATE INDEX idx_pos_shifts_register ON pos_shifts (register_id, opened_at DESC);

-- Each POS sale and return remembers the shift it was rung up in.
ALTER TABLE invoices ADD COLUMN pos_shift_id UUID REFERENCES pos_shifts(id);
CREATE INDEX idx_invoices_pos_shift ON invoices (pos_shift_id) WHERE pos_shift_id IS NOT NULL;

-- A till resends a sale when the reply is lost; it must be recorded once.
-- Earlier duplicates (possible before this) keep their invoices but get a
-- distinct ref so the rule can hold from now on.
UPDATE invoices i SET source_ref = i.source_ref || ':dup:' || i.id
WHERE i.source = 'pos' AND i.number LIKE 'POS-%' AND i.source_ref IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM invoices o
    WHERE o.org_id = i.org_id AND o.source = 'pos' AND o.number LIKE 'POS-%'
      AND o.source_ref = i.source_ref AND (o.created_at, o.id) < (i.created_at, i.id));
CREATE UNIQUE INDEX idx_invoices_pos_sale_once ON invoices (org_id, source_ref)
    WHERE source = 'pos' AND number LIKE 'POS-%' AND source_ref IS NOT NULL;

-- M-Pesa paid straight to the shop's till or paybill number and confirmed
-- by the cashier (most Kenyan shop payments), apart from Pesapal checkout.
ALTER TABLE payments DROP CONSTRAINT payments_method_check;
ALTER TABLE payments ADD CONSTRAINT payments_method_check
    CHECK (method IN ('cash', 'card', 'pos', 'bank_transfer', 'refund', 'pesapal', 'mpesa', 'other'));

ALTER TABLE pos_shifts FORCE ROW LEVEL SECURITY;
ALTER TABLE invoices FORCE ROW LEVEL SECURITY;
ALTER TABLE pos_registers FORCE ROW LEVEL SECURITY;
