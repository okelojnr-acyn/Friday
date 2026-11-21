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

export const returnPosSale = (number: string, shiftId?: string) =>
  api.post<PosSale>(
    `/api/invoicing/pos/sales/${encodeURIComponent(number)}/return${shiftId ? `?shift_id=${encodeURIComponent(shiftId)}` : ""}`,
  );

/** Starts a real Pesapal checkout for the built sale payload (same shape
 * PosPage.tsx already sends to /pos/sales -- this is a different
 * endpoint, not a different body). Unlike a cash/card sale, nothing is
 * recorded as paid yet: the returned redirect_url is where the customer
 * completes payment, and pollPosSaleStatus is how the register finds out
 * what happened. See apps/invoicing/app/main.py's pay_with_pesapal. */
export const startPesapalPosPayment = (sale: unknown) =>
  api.post<{ invoice_id: string; redirect_url: string }>("/api/invoicing/pos/sales/pay-with-pesapal", sale);

/** A POS sale paid through the business's own Paystack (card, M-Pesa,
 * bank): same body as a sale, paid only once Paystack confirms it (see
 * apps/invoicing/app/paystack_pay.py). pollPosSaleStatus also asks
 * Paystack, so the till finds out even if the webhook is lost. */
export const startPaystackPosPayment = (sale: unknown) =>
  api.post<{ invoice_id: string; redirect_url: string; prompt?: string }>(
    "/api/invoicing/pos/sales/pay-with-paystack",
    sale,
  );

/** A Paystack page for an invoice's balance, to send to the customer. */
export const paystackInvoiceLink = (invoiceId: string) =>
  api.post<{ invoice_id: string; redirect_url: string }>(`/api/invoicing/invoices/${invoiceId}/paystack-link`);

/** Every method a business or till can offer (kernel org settings and
 * invoicing's registers.py keep the same list). */
export const PAYMENT_METHODS = ["cash", "mpesa", "card", "paystack", "pesapal"];

export const PAYMENT_METHOD_LABEL: Record<string, string> = {
  cash: "Cash",
  mpesa: "M-Pesa to your till or paybill",
  card: "Card on your PDQ",
  paystack: "Paystack (card, M-Pesa, bank)",
  pesapal: "Pesapal",
};

/** What a till offers: its own list, else the business's, else all. */
export function offeredMethods(till?: string[] | null, business?: string[]): string[] {
  return till ?? business ?? PAYMENT_METHODS;
}

/** Cancels a sale still waiting on Paystack (checked with Paystack
 * first: a paid one stays paid). returned_cents is the till's own part
 * of a split, to hand back. */
export const cancelPosSale = (invoiceId: string) =>
  api.post<{ invoice_id: string; status: string; returned_cents: number }>(
    `/api/invoicing/pos/sales/${invoiceId}/cancel`,
  );

export const pollPosSaleStatus = (invoiceId: string) =>
  api.get<{ invoice_id: string; status: string }>(`/api/invoicing/pos/sales/${invoiceId}/status`);
