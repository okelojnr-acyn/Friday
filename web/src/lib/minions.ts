import { api, ApiError } from "./api";
import { shrinkPhoto } from "./productImages";
import { KERNEL_URL } from "./runtimeConfig";
import { loadSession } from "./session";

export interface ExpenseClaim {
  id: string;
  employee_id: string;
  description: string;
  amount_cents: number;
  currency: string;
  status: "submitted" | "approved" | "rejected" | "paid" | "withdrawn";
  receipt_url: string;
  /** false: the business paid (recorded only). Missing on older Minions = true. */
  reimburse?: boolean;
  /** "" or missing: no receipt photo. */
  receipt_sha?: string;
  submitted_at: string;
  /** HR plan phase 1; missing on an older Minions. */
  waiting_on_name?: string;
  decision_note?: string;
  decided_by_name?: string;
  paid_method?: string;
  paid_reference?: string;
}

/** Claims waiting for my decision (owners and admins: all waiting ones).
 * An older Minions ignores `waiting` and returns everything I can see. */
export const fetchClaimsWaitingForMe = async () =>
  (
    await api.get<ExpenseClaim[]>("/api/minions/expense_claims?waiting=true")
  ).filter((c) => c.status === "submitted");

/** A rejected claim of mine, fixed and sent again. */
export const resendExpenseClaim = (
  id: string,
  body: { description?: string; amount_cents?: number },
) => api.post<ExpenseClaim>(`/api/minions/expense_claims/${id}/resend`, body);

export interface ExpenseClaimCreate {
  description: string;
  amount_cents: number;
  currency?: string;
  receipt_url?: string;
  reimburse?: boolean;
}

export const fetchMyExpenseClaims = () =>
  api.get<ExpenseClaim[]>("/api/minions/expense_claims?mine=true");

export const submitExpenseClaim = (body: ExpenseClaimCreate) =>
  api.post<ExpenseClaim>("/api/minions/expense_claims", body);

/** Takes back your own claim while it still waits. */
export const withdrawExpenseClaim = (id: string) =>
  api.post<ExpenseClaim>(`/api/minions/expense_claims/${id}/withdraw`);

export interface WalletLink {
  wallet_address: string;
  wallet_network: string;
}

export const fetchMyWallet = () =>
  api.get<WalletLink>("/api/minions/me/wallet");

export const setMyWallet = (body: WalletLink) =>
  api.put<WalletLink>("/api/minions/me/wallet", body);

export interface MyPayrollLine {
  payroll_run_id: string;
  period_start: string;
  period_end: string;
  run_status: string;
  gross_amount_cents: number;
  currency: string;
  line_status: string;
}

export const fetchMyPayroll = () =>
  api.get<MyPayrollLine[]>("/api/minions/me/payroll");

async function receiptFetch(id: string, init?: RequestInit): Promise<Response> {
  const token = loadSession()?.token;
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(
    `${KERNEL_URL}/api/minions/expense_claims/${id}/receipt`,
    { ...init, headers },
  );
  if (!res.ok) {
    let message = res.statusText;
    try {
      message = (await res.json()).detail ?? message;
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, message);
  }
  return res;
}

/** Adds the receipt photo to your own waiting claim (resized to 1280 px). */
export async function uploadClaimReceipt(
  id: string,
  file: File,
): Promise<ExpenseClaim> {
  const blob = await shrinkPhoto(file, 1280);
  const res = await receiptFetch(id, {
    method: "PUT",
    body: blob,
    headers: { "Content-Type": blob.type },
  });
  return (await res.json()) as ExpenseClaim;
}

/** A claim's receipt photo (claimant, or whoever can see their claims). */
export const claimReceiptBlob = async (id: string): Promise<Blob> =>
  (await receiptFetch(id)).blob();

/** Opens a claim's receipt photo in a new tab. */
export async function openClaimReceipt(id: string): Promise<void> {
  const tab = window.open("", "_blank");
  const blob = await (await receiptFetch(id)).blob();
  const url = URL.createObjectURL(blob);
  if (tab) tab.location.href = url;
  else window.location.href = url;
}
