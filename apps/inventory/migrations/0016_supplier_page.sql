-- The supplier page (plan 12.6): the supplier acknowledges an order, says
-- it's dispatched, and adds their invoice (number, date and the file).
ALTER TABLE purchase_orders ADD COLUMN supplier_status TEXT NOT NULL DEFAULT ''
    CHECK (supplier_status IN ('', 'acknowledged', 'dispatched'));
ALTER TABLE purchase_orders ADD COLUMN supplier_note TEXT NOT NULL DEFAULT '';
ALTER TABLE purchase_orders ADD COLUMN supplier_updated_at TIMESTAMPTZ;
ALTER TABLE purchase_orders ADD COLUMN invoice_file_sha TEXT NOT NULL DEFAULT '';

CREATE TABLE po_invoice_files (
    po_id        UUID PRIMARY KEY REFERENCES purchase_orders(id) ON DELETE CASCADE,
    org_id       UUID NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('application/pdf', 'image/jpeg', 'image/png', 'image/webp')),
    data         BYTEA NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE po_invoice_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE po_invoice_files FORCE ROW LEVEL SECURITY;
CREATE POLICY po_invoice_files_org_isolation ON po_invoice_files
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
