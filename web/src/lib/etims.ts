import { api, ApiError } from "./api";
import { downloadTextFile } from "./csv";
import { KERNEL_URL } from "./runtimeConfig";
import { loadSession } from "./session";

/** KRA eTIMS codes (OSCU specification v2.0, section 4) and the filing
 * API (apps/invoicing/app/etims_routes.py). */

export const PACKAGING_UNITS: Record<string, string> = {
  NT: "Net (no packaging)",
  BG: "Bag",
  BX: "Box",
  BQ: "Bottle",
  CA: "Can",
  CT: "Carton",
  CR: "Crate",
  DR: "Drum",
  JR: "Jar",
  JY: "Jerrycan",
  PG: "Plate",
  RL: "Reel",
  RO: "Roll",
  TY: "Tank",
  OU: "Non-exterior packaging",
};

export interface EtimsRow {
  id: string;
  number: string;
  credit_note: boolean;
  original_number: string | null;
  original_etims_no: string;
  issued_at: string | null;
  buyer_pin: string;
  buyer_name: string;
  pin_ok: boolean;
  total_cents: number;
  vat_cents: number;
  by_code: Record<string, { gross_cents: number; vat_cents: number }>;
  status: "unfiled" | "submitted" | "failed";
  via: string;
  etims_invoice_no: string;
  filed_at: string | null;
  filed_by: string;
  error: string;
  receipt_check_url: string;
}

export interface EtimsLine {
  name: string;
  quantity: number;
  quantity_unit: string;
  unit_price_cents: number;
  discount_cents: number;
  tax_code: string;
  gross_cents: number;
  vat_cents: number;
  item_code: string;
}

const base = "/api/invoicing/etims";

export const listEtims = (scope: "pin" | "all", status: string, month: string) =>
  api.get<EtimsRow[]>(`${base}/invoices?scope=${scope}&status=${status}&month=${month}`);
export const etimsDetail = (id: string) => api.get<{ invoice: EtimsRow; lines: EtimsLine[] }>(`${base}/invoices/${id}`);
export const recordFiled = (id: string, no: string) => api.post<EtimsRow>(`${base}/invoices/${id}/filed`, { etims_invoice_no: no });
export const undoFiled = (id: string) => api.post<EtimsRow>(`${base}/invoices/${id}/unfile`);
export const setBuyer = (id: string, pin: string, name: string) => api.put<EtimsRow>(`${base}/invoices/${id}/buyer`, { pin, name });
export const sendToKra = () => api.post<{ sent: number; failed: number }>(`${base}/send`);

/** The month's VAT sales schedule (iTax VAT3 Section B columns). */
export async function downloadVatSales(month: string): Promise<void> {
  const session = loadSession();
  const res = await fetch(`${KERNEL_URL}${base}/vat-sales.csv?month=${month}`, {
    headers: session ? { Authorization: `Bearer ${session.token}` } : {},
  });
  if (!res.ok) throw new ApiError(res.status, "Could not download the VAT sales.");
  downloadTextFile(`vat-sales-${month}.csv`, await res.text());
}
