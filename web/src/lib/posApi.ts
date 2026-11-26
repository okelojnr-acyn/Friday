import { api } from "./api";

/** Registers (tills) and their shifts: apps/invoicing/app/registers.py. */

export interface PosShift {
  id: string;
  register_id: string | null;
  opened_at: string;
  closed_at: string | null;
  opening_float_cents: number;
  closing_count_cents: number | null;
  expected_cents: number | null;
  status: "open" | "closed";
  opened_by_email: string | null;
  closed_by_email: string | null;
  close_note: string;
  summary: {
    by_method: Record<string, { count: number; cents: number }>;
    sales: number;
    returns: number;
    /** Spending plan part C; missing on an older Invoicing. */
    paid_out_cents?: number;
    expected_cash_cents: number;
  } | null;
}

export interface PosRegister {
  id: string;
  name: string;
  location_name: string;
  active: boolean;
  /** The kernel location it stands in (plan section 12); null = not set. */
  location_id?: string | null;
  /** This till's own payment methods; null follows the business's. */
  payment_methods?: string[] | null;
  open_shift: PosShift | null;
}

export const listRegisters = () => api.get<PosRegister[]>("/api/invoicing/pos/registers");

export const createRegister = (name: string, locationName: string, locationId: string | null = null) =>
  api.post<PosRegister>("/api/invoicing/pos/registers", { name, location_name: locationName, location_id: locationId });

export const updateRegister = (
  id: string,
  patch: {
    name?: string;
    location_name?: string;
    location_id?: string | null;
    active?: boolean;
    payment_methods?: string[] | null;
  },
) =>
  api.patch<PosRegister>(`/api/invoicing/pos/registers/${id}`, patch);

// registerId null: the org's only till (set up in Business settings).
export const openShift = (registerId: string | null, openingFloatCents: number) =>
  api.post<PosShift>("/api/invoicing/pos/shifts/open", {
    register_id: registerId,
    opening_float_cents: openingFloatCents,
  });

export const closeShift = (shiftId: string, closingCountCents: number, note: string) =>
  api.post<PosShift>(`/api/invoicing/pos/shifts/${shiftId}/close`, {
    closing_count_cents: closingCountCents,
    note,
  });

// This device's till, remembered across visits.
const REGISTER_KEY = "friday.pos.register_id";

export function deviceRegisterId(): string | null {
  try {
    return localStorage.getItem(REGISTER_KEY);
  } catch {
    return null;
  }
}

export function setDeviceRegisterId(id: string | null) {
  try {
    if (id) localStorage.setItem(REGISTER_KEY, id);
    else localStorage.removeItem(REGISTER_KEY);
  } catch {
    // storage blocked: the till asks again next time
  }
}

/** "1,250.50" typed on a keypad -> cents. */
export function keypadToCents(entry: string): number {
  const n = Number.parseFloat(entry || "0");
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}
