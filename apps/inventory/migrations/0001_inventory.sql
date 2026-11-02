CREATE TABLE products (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL,
    name            TEXT NOT NULL,
    sku             TEXT NOT NULL DEFAULT '',
    barcode         TEXT NOT NULL DEFAULT '',
    price_cents     BIGINT NOT NULL DEFAULT 0,
    cost_cents      BIGINT NOT NULL DEFAULT 0,
    on_hand_qty     INTEGER NOT NULL DEFAULT 0,
    track_inventory BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_products_org ON products(org_id);
-- Barcode lookups are the hot path at checkout; partial index since most
-- rows won't have a code (free-text default '').
CREATE INDEX idx_products_org_barcode ON products(org_id, barcode) WHERE barcode <> '';

CREATE TABLE stock_moves (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL,
    product_id    UUID NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    product_name  TEXT NOT NULL,
    qty_delta     INTEGER NOT NULL,
    reason        TEXT NOT NULL DEFAULT 'manual_adjustment'
                  CHECK (reason IN ('manual_adjustment', 'pos_sale', 'received')),
    reference     TEXT NOT NULL DEFAULT '',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_stock_moves_org ON stock_moves(org_id);
CREATE INDEX idx_stock_moves_product ON stock_moves(product_id);

-- Row-Level Security: see apps/crm/migrations for the full explanation.
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE products FORCE ROW LEVEL SECURITY;
CREATE POLICY products_org_isolation ON products
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

ALTER TABLE stock_moves ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_moves FORCE ROW LEVEL SECURITY;
CREATE POLICY stock_moves_org_isolation ON stock_moves
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
