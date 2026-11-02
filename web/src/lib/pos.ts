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
