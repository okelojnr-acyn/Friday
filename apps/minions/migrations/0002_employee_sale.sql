-- Traces a completed POS sale back to the employee who rang it up.
-- Subscribed to invoicing.pos_sale.recorded (see
-- kernel/internal/gateway/events.go) -- the unique index on
-- (org_id, invoice_number) is both the natural key and the idempotency
-- guard against at-least-once event delivery (same role
-- (org_id, source, source_ref) plays for accounting's journal entries).
CREATE TABLE employee_sales (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    employee_id     UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    employee_name   TEXT NOT NULL,
    invoice_number  TEXT NOT NULL,
    amount_cents    BIGINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_employee_sales_org ON employee_sales(org_id);
CREATE INDEX idx_employee_sales_employee ON employee_sales(employee_id);
CREATE UNIQUE INDEX idx_employee_sales_org_invoice ON employee_sales(org_id, invoice_number);
ALTER TABLE employee_sales ENABLE ROW LEVEL SECURITY;
ALTER TABLE employee_sales FORCE ROW LEVEL SECURITY;
CREATE POLICY employee_sales_org_isolation ON employee_sales
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
