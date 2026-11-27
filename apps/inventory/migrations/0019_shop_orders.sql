-- Online shop orders (Friday Host STOREFRONT-PLAN.md, Commerce slice 2).
-- Placed from the shop's page through the kernel's public routes; every
-- price and total is Inventory's, never the page's. The shopper follows
-- it with a tracking token (only its hash is kept). Paying (slice 3)
-- turns it into an invoice; staff move it along (slice 4).
CREATE TABLE shop_orders (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL,
    number        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'placed'
                  CHECK (status IN ('placed', 'paid', 'ready', 'completed', 'cancelled')),
    customer_name TEXT NOT NULL,
    phone         TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    fulfilment    TEXT NOT NULL CHECK (fulfilment IN ('pickup', 'delivery')),
    address       TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    total_cents   BIGINT NOT NULL CHECK (total_cents >= 0),
    token_hash    TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, number)
);
CREATE INDEX idx_shop_orders_org ON shop_orders(org_id, created_at DESC);

CREATE TABLE shop_order_lines (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           UUID NOT NULL,
    order_id         UUID NOT NULL REFERENCES shop_orders(id) ON DELETE CASCADE,
    product_id       UUID REFERENCES products(id) ON DELETE SET NULL,
    name             TEXT NOT NULL,
    variant_name     TEXT NOT NULL DEFAULT '',
    unit_price_cents BIGINT NOT NULL CHECK (unit_price_cents >= 0),
    quantity         INTEGER NOT NULL CHECK (quantity BETWEEN 1 AND 999),
    total_cents      BIGINT NOT NULL CHECK (total_cents >= 0)
);
CREATE INDEX idx_shop_order_lines_order ON shop_order_lines(order_id);

ALTER TABLE shop_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE shop_orders FORCE ROW LEVEL SECURITY;
CREATE POLICY shop_orders_org_isolation ON shop_orders
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
ALTER TABLE shop_order_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE shop_order_lines FORCE ROW LEVEL SECURITY;
CREATE POLICY shop_order_lines_org_isolation ON shop_order_lines
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);
