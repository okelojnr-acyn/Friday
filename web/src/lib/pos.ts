import { api } from "./api";

export interface PosSale {
  id: string;
  number: string;
  status: string;
  currency: string;
  total_cents: number;
  paid_cents: number;
  created_at: string;
}

export const fetchPosSale = (number: string) => api.get<PosSale>(`/api/invoicing/pos/sales/${number}`);

export const returnPosSale = (number: string) => api.post<PosSale>(`/api/invoicing/pos/sales/${number}/return`);

/** Starts a real Pesapal checkout for the built sale payload (same shape
 * PosPage.tsx already sends to /pos/sales -- this is a different
 * endpoint, not a different body). Unlike a cash/card sale, nothing is
 * recorded as paid yet: the returned redirect_url is where the customer
 * completes payment, and pollPosSaleStatus is how the register finds out
 * what happened. See apps/invoicing/app/main.py's pay_with_pesapal. */
export const startPesapalPosPayment = (sale: unknown) =>
  api.post<{ invoice_id: string; redirect_url: string }>("/api/invoicing/pos/sales/pay-with-pesapal", sale);

export const pollPosSaleStatus = (invoiceId: string) =>
  api.get<{ invoice_id: string; status: string }>(`/api/invoicing/pos/sales/${invoiceId}/status`);
