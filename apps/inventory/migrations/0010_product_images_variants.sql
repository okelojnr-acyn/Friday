-- Product photos and variants (owner, 2026-11-16).

-- One photo per product, resized in the browser (512 px WebP, tens of KB)
-- and kept here, so it is backed up with everything else and needs no
-- separate file store. image_sha on the product changes when the photo
-- does, so tills can cache it for good under that key.
CREATE TABLE product_images (
    product_id   UUID PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
    org_id       UUID NOT NULL,
    content_type TEXT NOT NULL CHECK (content_type IN ('image/webp', 'image/jpeg', 'image/png')),
    data         BYTEA NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE product_images ENABLE ROW LEVEL SECURITY;
ALTER TABLE product_images FORCE ROW LEVEL SECURITY;
CREATE POLICY product_images_org_isolation ON product_images
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

ALTER TABLE products ADD COLUMN image_sha TEXT NOT NULL DEFAULT '';

-- Variants: "Sugar" with 1 kg and 2 kg. A variant is a full product
-- (its own price, SKU, barcode, stock) that names the product it is a
-- variant of; the till shows one tile and asks which.
ALTER TABLE products ADD COLUMN variant_of UUID REFERENCES products(id) ON DELETE SET NULL;
ALTER TABLE products ADD COLUMN variant_name TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_products_variant_of ON products (org_id, variant_of) WHERE variant_of IS NOT NULL;
