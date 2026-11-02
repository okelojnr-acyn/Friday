import { api } from "./api";

export interface Product {
  id: string;
  name: string;
  sku: string;
  barcode: string;
  price_cents: number;
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
