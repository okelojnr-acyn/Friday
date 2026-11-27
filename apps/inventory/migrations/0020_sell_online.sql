-- Online shop (Commerce slice 4): a product can be kept off the shop.
-- On by default: a business that opens a shop sells what it prices.
ALTER TABLE products ADD COLUMN IF NOT EXISTS sell_online BOOLEAN NOT NULL DEFAULT true;
