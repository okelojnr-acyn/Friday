import { api } from "./api";

export interface ExpenseClaim {
  id: string;
  employee_id: string;
  description: string;
  amount_cents: number;
  currency: string;
  status: "submitted" | "approved" | "rejected" | "paid";
  receipt_url: string;
  submitted_at: string;
}

export interface ExpenseClaimCreate {
  description: string;
  amount_cents: number;
  currency?: string;
  receipt_url?: string;
}

export const fetchMyExpenseClaims = () => api.get<ExpenseClaim[]>("/api/minions/expense_claims?mine=true");

export const submitExpenseClaim = (body: ExpenseClaimCreate) =>
  api.post<ExpenseClaim>("/api/minions/expense_claims", body);

export interface WalletLink {
  wallet_address: string;
  wallet_network: string;
}

export const fetchMyWallet = () => api.get<WalletLink>("/api/minions/me/wallet");

export const setMyWallet = (body: WalletLink) => api.put<WalletLink>("/api/minions/me/wallet", body);

export interface MyPayrollLine {
  payroll_run_id: string;
  period_start: string;
  period_end: string;
  run_status: string;
  gross_amount_cents: number;
  currency: string;
  line_status: string;
}

export const fetchMyPayroll = () => api.get<MyPayrollLine[]>("/api/minions/me/payroll");
