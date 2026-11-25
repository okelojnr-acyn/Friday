import { loadSession, clearSession, saveSession } from "./session";
import type { Session } from "./types";

// Everything goes through the kernel (ARCHITECTURE.md: "web/ ... talks
// only to the kernel"). /api/{app}/* is reverse-proxied by
// kernel/internal/gateway/proxy.go, which strips the "/api/{app}" prefix
// and forwards the bearer token through unchanged.
import { KERNEL_URL } from "./runtimeConfig";

export class ApiError extends Error {
  status: number;
  /** The error body's other fields (e.g. a machine-readable `code`). */
  data: Record<string, unknown>;
  constructor(status: number, message: string, data: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

/** Swaps the token for a fresh one with the person's access as it is now
 * (kernel POST /auth/refresh); false when the kernel says sign in again. */
async function refreshSession(token: string): Promise<boolean> {
  try {
    const res = await fetch(`${KERNEL_URL}/auth/refresh`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return false;
    const r = (await res.json()) as { token: string; org_id: string; role: Session["role"]; email: string };
    saveSession({ token: r.token, orgId: r.org_id, role: r.role, email: r.email });
    return true;
  } catch {
    return false;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const session = loadSession();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (session) headers.set("Authorization", `Bearer ${session.token}`);

  let res: Response;
  try {
    res = await fetch(`${KERNEL_URL}${path}`, { ...init, headers });
  } catch {
    // fetch() only rejects when the browser got no usable response at
    // all -- offline, DNS, or a CORS rejection (2026-11-10: crm/invoicing
    // sent a stale Access-Control-Allow-Origin and every page fell back
    // to a generic "Could not load ..." with nothing to go on). Status 0
    // so callers' `instanceof ApiError` paths show this instead.
    throw new ApiError(0, `Can't reach the Friday server (${path.split("?")[0]}) — network or CORS problem`);
  }

  if (res.status === 401 && session && path !== "/auth/refresh") {
    const body = await res.clone().json().catch(() => ({}));
    if (body?.code === "access_changed" && (await refreshSession(session.token))) {
      // Their role or jobs changed: every screen reads them once, so reload.
      window.location.reload();
      return new Promise<T>(() => {}); // the page is going away
    }
  }
  if (res.status === 401) {
    clearSession();
  }

  if (!res.ok) {
    let message = res.statusText;
    try {
      const body = await res.json();
      message = body.error ?? body.detail ?? message;
    } catch {
      // body wasn't JSON (or was empty) -- fall back to statusText
    }
    throw new ApiError(res.status, message);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// A short memory for GETs (owner, 2026-11-22: every move between pages
// re-read everything). Same path in flight = one request; a fresh answer
// is reused for `ttlMs`; any change (POST/PATCH/PUT/DELETE) forgets it
// all, so your own edits show at once. Keyed by org and person, so
// switching business or account never shows someone else's data.
// shortcut: another person's edit can take up to ttlMs to show; lower
// the TTLs (or add a "refresh") if that bites.
const memory = new Map<string, { at: number; value: Promise<unknown> }>();

function cachedGet<T>(path: string, ttlMs: number): Promise<T> {
  const session = loadSession();
  const key = `${session?.orgId ?? ""} ${session?.email ?? ""} ${path}`;
  const hit = memory.get(key);
  if (hit && Date.now() - hit.at < ttlMs) return hit.value as Promise<T>;
  const value = request<T>(path).catch((err) => {
    memory.delete(key);
    throw err;
  });
  memory.set(key, { at: Date.now(), value });
  return value;
}

async function change<T>(path: string, init: RequestInit): Promise<T> {
  memory.clear();
  try {
    return await request<T>(path, init);
  } finally {
    // A read that started during the change may hold the old answer.
    memory.clear();
  }
}

/** How long a read may be reused: settings-like reads for minutes, lists briefly. */
export const LONG = 10 * 60_000;
export const SHORT = 30_000;

export const api = {
  /** Always asks the server (polling, payment status, anything live). */
  get: <T>(path: string) => request<T>(path),
  /** Reuses a recent answer; see cachedGet. */
  cached: <T>(path: string, ttlMs: number) => cachedGet<T>(path, ttlMs),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
    change<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined, headers }),
  patch: <T>(path: string, body?: unknown) =>
    change<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    change<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => change<T>(path, { method: "DELETE" }),
};

/** Naive but exhaustive against the current registry: every resource
 * name pluralizes with a trailing "s" (opportunity -> opportunities,
 * customer -> customers, invoice -> invoices, project -> projects,
 * task -> tasks, ticket -> tickets). Revisit if an irregular plural
 * shows up. */
export function pluralize(name: string): string {
  if (name.endsWith("y") && !/[aeiou]y$/i.test(name)) {
    return name.slice(0, -1) + "ies";
  }
  return name + "s";
}

// Routes whose path isn't the resource name + "s". Found 2026-11-16: the
// Units of Measure page answered "Not Found" (unit_of_measures). Every
// other registered resource was checked against its app's routes.
const PATH_OVERRIDES: Record<string, string> = {
  "inventory.unit_of_measure": "units_of_measure",
  "invoicing.pos_shift": "pos/shifts",
};

export function resourceBasePath(app: string, resourceName: string): string {
  return `/api/${app}/${PATH_OVERRIDES[`${app}.${resourceName}`] ?? pluralize(resourceName)}`;
}
