// Cashier PIN (plan section 11). A till a manager trusted keeps a device
// token; on that till only, cashiers can sign in with a 6-digit PIN. The
// session it gives reaches selling and shifts, nothing else.
import { api, ApiError } from "./api";
import { KERNEL_URL } from "./runtimeConfig";

const DEVICE_KEY = "friday.pos.device";

export function posDeviceToken(): string | null {
  try {
    return localStorage.getItem(DEVICE_KEY);
  } catch {
    return null;
  }
}

/** The id of this till's own trust entry, to mark it in the list. */
export function posDeviceId(): string | null {
  try {
    return localStorage.getItem(DEVICE_KEY + ".id");
  } catch {
    return null;
  }
}

function setPosDeviceToken(token: string | null, id?: string) {
  try {
    if (token) {
      localStorage.setItem(DEVICE_KEY, token);
      if (id) localStorage.setItem(DEVICE_KEY + ".id", id);
    } else {
      localStorage.removeItem(DEVICE_KEY);
      localStorage.removeItem(DEVICE_KEY + ".id");
    }
  } catch {
    // private window: the till just isn't remembered
  }
}

export interface PosCashier {
  user_id: string;
  name: string;
  email?: string;
  role?: string;
  has_pin: boolean;
  locked_until: string | null;
}

export interface PosDevice {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface PosPinEvent {
  kind: string;
  name: string;
  device: string;
  created_at: string;
}

async function deviceFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = posDeviceToken();
  let res: Response;
  try {
    res = await fetch(`${KERNEL_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", "X-Pos-Device": token ?? "" },
    });
  } catch {
    throw new ApiError(0, "Can't reach the Friday server. Check the connection.");
  }
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    // This till's trust was revoked: forget it, so it asks for a passkey.
    if (body.code === "device_not_enrolled") setPosDeviceToken(null);
    throw new ApiError(res.status, body.error ?? res.statusText, body);
  }
  return body as T;
}

/** The signed-in cashier's own PIN resumes their locked till (plan 20.3);
 * a trusted till says so, an untrusted one resumes a passkey session. */
export const resumeTill = (pin: string) =>
  api.post<void>("/auth/pos/resume", { pin }, { "X-Pos-Device": posDeviceToken() ?? "" });

export const listPosCashiers = () => deviceFetch<PosCashier[]>("/auth/pos/cashiers");

export const pinLogin = (userId: string, pin: string) =>
  deviceFetch<{ token: string; org_id: string; role: "owner" | "admin" | "member" | "viewer"; email: string }>(
    "/auth/pos/pin",
    { method: "POST", body: JSON.stringify({ user_id: userId, pin }) },
  );

/** A team leader's or manager's PIN on this trusted till approving one
 * staff action (a return), for two minutes. */
export const approveAtTill = (userId: string, pin: string) =>
  deviceFetch<{ approval: string }>("/auth/pos/approve", { method: "POST", body: JSON.stringify({ user_id: userId, pin }) });

export async function trustThisTill(name: string): Promise<PosDevice> {
  const d = await api.post<PosDevice & { token: string }>("/pos/devices", { name });
  setPosDeviceToken(d.token, d.id);
  return d;
}

export function forgetThisTill() {
  setPosDeviceToken(null);
}

export const listPosDevices = () => api.get<PosDevice[]>("/pos/devices");
export const revokePosDevice = (id: string) => api.del<void>(`/pos/devices/${id}`);
export const myPosPin = () => api.get<{ has_pin: boolean }>("/pos/pin");
export const setMyPosPin = (pin: string) => api.put<void>("/pos/pin", { pin });
export const listPosPins = () => api.get<PosCashier[]>("/pos/pins");
export const setPosPinFor = (userId: string, pin: string) => api.put<void>(`/pos/pins/${userId}`, { pin });
export const unlockPosPin = (userId: string) => api.post<void>(`/pos/pins/${userId}/unlock`);
export const clearPosPin = (userId: string) => api.del<void>(`/pos/pins/${userId}`);
export const listPosPinEvents = () => api.get<PosPinEvent[]>("/pos/pin-events");
