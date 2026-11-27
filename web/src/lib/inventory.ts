import { api } from "./api";
import type { RecordRow } from "./types";

export interface Product {
  id: string;
  name: string;
  kind: "product" | "service";
  sku: string;
  barcode: string;
  category?: string;
  image_sha?: string;
  variant_of?: string | null;
  variant_name?: string;
  price_cents: number;
  cost_cents: number;
  on_hand_qty: number;
  track_inventory: boolean;
  /** Shown in the online shop (Business settings > Online shop). */
  sell_online?: boolean;
  reorder_point?: number;
  /** Stock is kept in the base unit; one purchase/sales unit holds
   * purchase_factor/sales_factor base units. Price is per sales unit,
   * cost per base unit. */
  base_uom_id?: string | null;
  purchase_uom_id?: string | null;
  purchase_factor?: number;
  sales_uom_id?: string | null;
  sales_factor?: number;
  /** eTIMS tax type A-E; "" = the business's default rate. */
  tax_code?: string;
  etims_item_class?: string;
  etims_packaging_unit?: string;
  etims_item_code?: string;
}

/** Best-effort: the inventory app may not be installed for this org, in
 * which case the POS register just falls back to freeform-only entry
 * (no product catalog, no barcode scanning) rather than erroring. */
/** The shelf. Throws when it can't be read, so the till can say why
 * instead of "no products yet" (a refused PIN sign-in looked like an
 * empty shop, 2026-11-22). */
export const fetchProductCatalog = () => api.get<Product[]>("/api/inventory/products");

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

/** The till's warning when an order asks for more than the shelf should
 * have (plan 20.2 #3): the sale still goes through (the shelf is the
 * truth), the cashier is told, and the count goes negative for a recount.
 * Null when there's enough, or the product isn't counted. */
export function shortWarning(
  p: { name: string; on_hand_qty: number; track_inventory: boolean; sales_factor?: number },
  qtyInOrder: number,
): string | null {
  if (!p.track_inventory) return null;
  const onHand = Number(p.on_hand_qty);
  const factor = p.sales_factor ?? 1;
  if (qtyInOrder * factor <= onHand) return null;
  const left = Math.max(0, Math.floor(onHand / factor));
  return `Only ${left} ${p.name} on record. Selling anyway; count it when you can.`;
}
