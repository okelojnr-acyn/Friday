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
  /** Spending plan part A; missing on an older Minions. */
  for_kind?: ForKind;
  for_id?: string;
  for_label?: string;
  category?: string;
  paid_from?: PaidFrom;
  no_receipt_reason?: string;
  etims_invoice_no?: string;
  /** Spending plan part B; missing on an older Minions. */
  request_id?: string | null;
  emergency_reason?: string;
  /** e.g. "not asked first", "24% over the approved 5,000". */
  flag?: string;
  /** Part C: the petty cash float it came out of. */
  float_id?: string | null;
}

export type ForKind = "daily" | "task" | "project" | "vehicle" | "trip" | "meeting";
export type PaidFrom = "own" | "petty_cash" | "business";
export const CATEGORIES = [
  ["transport", "Transport"],
  ["fuel", "Fuel"],
  ["meals", "Meals"],
  ["accommodation", "Accommodation"],
  ["airtime", "Airtime and data"],
  ["supplies", "Supplies"],
  ["repairs", "Repairs"],
  ["cleaning", "Cleaning"],
  ["other", "Other"],
] as const;

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
  paid_from?: PaidFrom;
  for_kind?: ForKind;
  for_id?: string;
  for_label?: string;
  category?: string;
  no_receipt_reason?: string;
  etims_invoice_no?: string;
  request_id?: string;
  emergency_reason?: string;
  /** Petty cash: which float it came out of. */
  float_id?: string;
  billable?: boolean;
  customer_id?: string;
  customer_name?: string;
}

/** Petty cash (spending plan part C): a float per location, one holder.
 * balance/pending/moves only for the holder and those who pay people. */
export interface PettyFloat {
  id: string;
  name: string;
  location_id: string;
  holder_user_id: string;
  holder_name: string;
  float_cents: number;
  currency: string;
  balance_cents: number | null;
  pending_cents: number | null;
  held_by_me?: boolean;
  moves: { id: string; kind: "top_up" | "slip" | "count"; amount_cents: number; note: string; by_name: string; created_at: string }[];
}
const PETTY = "/api/minions/petty_cash";
/** An older Minions has no petty cash: none. */
export const fetchPettyCash = () =>
  api.get<PettyFloat[]>(PETTY).catch((err) => (err instanceof ApiError && err.status === 404 ? [] : Promise.reject(err)));
export const createPettyCash = (body: { name: string; location_id: string; holder_user_id: string; float_cents?: number }) =>
  api.post<PettyFloat>(PETTY, body);
export const topUpPettyCash = (id: string, method: string, reference: string) =>
  api.post<PettyFloat>(`${PETTY}/${id}/top_up`, { method, reference });
export const countPettyCash = (id: string, counted_cents: number, note: string) =>
  api.post<PettyFloat>(`${PETTY}/${id}/count`, { counted_cents, note });
export const fetchPettySlips = () =>
  api.get<ExpenseClaim[]>(`${PETTY}/slips`).catch(() => [] as ExpenseClaim[]);
export const confirmPettySlip = (claimId: string) => api.post<ExpenseClaim>(`${PETTY}/slips/${claimId}/confirm`);

/** Asking first (spending plan part B): a spend, or a trip with optional
 * cash up front. Claims go against it once approved. */
export interface SpendRequest {
  id: string;
  employee_id: string;
  kind: "spend" | "trip";
  description: string;
  amount_cents: number;
  currency: string;
  for_kind: ForKind;
  for_id: string;
  for_label: string;
  category: string;
  destination: string;
  starts_on: string | null;
  ends_on: string | null;
  advance_cents: number;
  status: "submitted" | "approved" | "rejected" | "withdrawn" | "closed";
  waiting_on_name: string;
  decision_note: string;
  decided_by_name: string;
  advance_paid_at: string | null;
  spent_cents: number;
  submitted_at: string;
}

export type SpendRequestCreate = Partial<
  Pick<SpendRequest, "kind" | "for_kind" | "for_id" | "for_label" | "category" | "destination" | "starts_on" | "ends_on" | "advance_cents">
> & { description: string; amount_cents: number };

const SPEND = "/api/minions/spend_requests";
/** An older Minions has no spend requests: an empty list. */
const orNone = (p: Promise<SpendRequest[]>) => p.catch((err) => (err instanceof ApiError && err.status === 404 ? [] : Promise.reject(err)));
export const fetchMySpendRequests = () => orNone(api.get<SpendRequest[]>(`${SPEND}?mine=true`));
export const fetchMyOpenRequests = () => orNone(api.get<SpendRequest[]>(`${SPEND}?mine=true&open=true`));
export const fetchRequestsWaitingForMe = () => orNone(api.get<SpendRequest[]>(`${SPEND}?waiting=true`));
export const fetchOpenTrips = () =>
  orNone(api.get<SpendRequest[]>(`${SPEND}?open=true`)).then((rs) => rs.filter((r) => r.kind === "trip"));
export const askFirst = (body: SpendRequestCreate) => api.post<SpendRequest>(SPEND, body);
export const withdrawSpendRequest = (id: string) => api.post<SpendRequest>(`${SPEND}/${id}/withdraw`);
export const payTripAdvance = (id: string, method: string, reference: string) =>
  api.post<SpendRequest>(`${SPEND}/${id}/advance`, { method, reference });
export const settleRequest = (id: string, method: string, reference: string) =>
  api.post<SpendRequest>(`${SPEND}/${id}/settle`, { method, reference });

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
  /** The payslip (Kenya); missing on an older Minions, 0 when none. */
  nssf_cents?: number;
  shif_cents?: number;
  levy_cents?: number;
  paye_cents?: number;
  net_cents?: number;
  advance_cents?: number;
  unpaid_days?: number;
  unpaid_cents?: number;
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
