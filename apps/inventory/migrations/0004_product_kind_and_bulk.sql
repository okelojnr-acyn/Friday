-- Makes "service" (no barcode, no stock) a first-class choice instead of
-- an implicit consequence of unchecking "Tracks stock" -- the bulk-add
-- screen and the product list both show this directly.
ALTER TABLE products ADD COLUMN kind TEXT NOT NULL DEFAULT 'product'
    CHECK (kind IN ('product', 'service'));
