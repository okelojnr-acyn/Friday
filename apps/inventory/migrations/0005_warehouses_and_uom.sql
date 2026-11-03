CREATE TABLE warehouses (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id     UUID NOT NULL,
    name       TEXT NOT NULL,
    code       TEXT NOT NULL DEFAULT '',
    address    TEXT NOT NULL DEFAULT '',
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_warehouses_org ON warehouses(org_id);
ALTER TABLE warehouses ENABLE ROW LEVEL SECURITY;
ALTER TABLE warehouses FORCE ROW LEVEL SECURITY;
CREATE POLICY warehouses_org_isolation ON warehouses
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

CREATE TABLE units_of_measure (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL,
    name         TEXT NOT NULL,
    abbreviation TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_uom_org ON units_of_measure(org_id);
ALTER TABLE units_of_measure ENABLE ROW LEVEL SECURITY;
ALTER TABLE units_of_measure FORCE ROW LEVEL SECURITY;
CREATE POLICY units_of_measure_org_isolation ON units_of_measure
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

-- Multi-warehouse, v1 scope: a product has one *default* warehouse
-- (for "where does new stock land by default") and every StockMove can
-- note which warehouse it happened at -- enough to filter/report
-- per-location without the bigger structural change of splitting
-- on_hand_qty into its own per-(product, warehouse) table. That split
-- is a documented stretch goal: StockMove already carries everything
-- needed to derive a real per-warehouse balance later (sum qty_delta
-- grouped by warehouse_id) without another migration.
ALTER TABLE products ADD COLUMN default_warehouse_id UUID REFERENCES warehouses(id) ON DELETE SET NULL;
ALTER TABLE stock_moves ADD COLUMN warehouse_id UUID REFERENCES warehouses(id) ON DELETE SET NULL;

-- Units of measure: how many of a product's *base* unit one of its
-- selling units represents (e.g. uom="Box of 12", conversion_factor=12
-- means on_hand_qty is tracked in individual units, but the product is
-- sold/received by the box). Defaults to 1 (uom doesn't change the
-- quantity math at all) so every existing product is unaffected.
ALTER TABLE products ADD COLUMN uom_id UUID REFERENCES units_of_measure(id) ON DELETE SET NULL;
ALTER TABLE products ADD COLUMN uom_conversion_factor NUMERIC(10, 4) NOT NULL DEFAULT 1;

-- Valuation method: a field only for v1, not a FIFO/average costing
-- engine -- StockMove already has every row needed to compute real
-- FIFO/average cost layers later (it's an append-only ledger with
-- qty_delta and reference per move); the gap is a cost-layer query, not
-- missing data. "standard" (Product.cost_cents as-is) is the only
-- method actually used by any code path today.
ALTER TABLE products ADD COLUMN valuation_method TEXT NOT NULL DEFAULT 'standard'
    CHECK (valuation_method IN ('standard', 'fifo', 'average'));
