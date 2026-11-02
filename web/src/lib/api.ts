import { loadSession, clearSession } from "./session";

// Everything goes through the kernel (ARCHITECTURE.md: "web/ ... talks
// only to the kernel"). /api/{app}/* is reverse-proxied by
// kernel/internal/gateway/proxy.go, which strips the "/api/{app}" prefix
// and forwards the bearer token through unchanged.
const KERNEL_URL = import.meta.env.VITE_KERNEL_URL ?? "http://localhost:8080";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const session = loadSession();
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  if (session) headers.set("Authorization", `Bearer ${session.token}`);

  const res = await fetch(`${KERNEL_URL}${path}`, { ...init, headers });

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

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
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

export function resourceBasePath(app: string, resourceName: string): string {
  return `/api/${app}/${pluralize(resourceName)}`;
}
