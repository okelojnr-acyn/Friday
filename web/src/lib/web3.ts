import { api } from "./api";

export interface Wallet {
  id: string;
  org_id: string;
  provider: string;
  network: string;
  address: string;
  currency: string;
  balance: string;
  updated_at: string;
}

export interface Transaction {
  id: string;
  org_id: string;
  kind: "payout" | "credit_transfer";
  external_id: string;
  status: string;
  amount: string;
  currency: string;
  network: string;
  to_address: string;
  reason: string;
  created_at: string;
  updated_at: string;
}

export interface PayoutRequest {
  to_address: string;
  currency: string;
  amount: string;
  network: string;
  reason: string;
}

export const fetchWallets = () => api.get<Wallet[]>("/api/web3/wallets");
export const refreshWallets = () => api.post<Wallet[]>("/api/web3/wallets/refresh");
export const fetchTransactions = () => api.get<Transaction[]>("/api/web3/transactions");
export const requestPayout = (body: PayoutRequest) => api.post<Transaction>("/api/web3/transactions/payout", body);
export const refreshTransactionStatus = (id: string) =>
  api.post<Transaction>(`/api/web3/transactions/${id}/refresh-status`);
