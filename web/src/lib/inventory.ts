import { api } from "./api";
import type { RecordRow } from "./types";

export interface Product {
  id: string;
  name: string;
  kind: "product" | "service";
  sku: string;
  barcode: string;
  price_cents: number;
  cost_cents: number;
  on_hand_qty: number;
  track_inventory: boolean;
}

/** Best-effort: the inventory app may not be installed for this org, in
 * which case the POS register just falls back to freeform-only entry
 * (no product catalog, no barcode scanning) rather than erroring. */
export async function fetchProductCatalog(): Promise<Product[]> {
  try {
    return await api.get<Product[]>("/api/inventory/products");
  } catch {
    return [];
  }
}

export interface ProductBulkRow {
  name: string;
  kind: "product" | "service";
  sku: string;
  barcode: string;
  price_cents: number;
  cost_cents: number;
  on_hand_qty: number;
  track_inventory: boolean;
}

/** apps/inventory/app/main.py's bulk_create_products -- one request for
 * every row the bulk-add-products panel collected, instead of one round
 * trip per row. */
export const bulkCreateProducts = (products: ProductBulkRow[]) =>
  api.post<RecordRow[]>("/api/inventory/products/bulk", { products });
