import { api } from "./api";

export interface Account {
  id: string;
  org_id: string;
  code: string;
  name: string;
  type: "asset" | "liability" | "equity" | "income" | "expense";
  parent_id: string | null;
  is_active: boolean;
  created_at: string;
}

export interface ReportLine {
  account_id: string;
  code: string;
  name: string;
  amount_cents: number;
}

export interface ProfitAndLoss {
  start_date: string;
  end_date: string;
  income: ReportLine[];
  expenses: ReportLine[];
  total_income_cents: number;
  total_expenses_cents: number;
  net_income_cents: number;
}

export interface BalanceSheet {
  as_of_date: string;
  assets: ReportLine[];
  liabilities: ReportLine[];
  equity: ReportLine[];
  net_income_to_date_cents: number;
  total_assets_cents: number;
  total_liabilities_cents: number;
  total_equity_cents: number;
}

export interface CashFlowBySource {
  source: string;
  net_cents: number;
}

export interface CashFlow {
  start_date: string;
  end_date: string;
  beginning_balance_cents: number;
  by_source: CashFlowBySource[];
  net_change_cents: number;
  ending_balance_cents: number;
}

export interface LedgerLine {
  journal_entry_id: string;
  number: string;
  entry_date: string;
  description: string;
  debit_cents: number;
  credit_cents: number;
  balance_cents: number;
}

export const fetchAccounts = () => api.get<Account[]>("/api/accounting/accounts");

export const fetchProfitAndLoss = (startDate: string, endDate: string) =>
  api.get<ProfitAndLoss>(`/api/accounting/reports/profit-and-loss?start_date=${startDate}&end_date=${endDate}`);

export const fetchBalanceSheet = (asOfDate: string) =>
  api.get<BalanceSheet>(`/api/accounting/reports/balance-sheet?as_of_date=${asOfDate}`);

export const fetchCashFlow = (startDate: string, endDate: string) =>
  api.get<CashFlow>(`/api/accounting/reports/cash-flow?start_date=${startDate}&end_date=${endDate}`);

export const fetchAccountLedger = (accountId: string) =>
  api.get<LedgerLine[]>(`/api/accounting/accounts/${accountId}/ledger`);
