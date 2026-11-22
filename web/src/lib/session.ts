import type { Session } from "./types";

// The till (pos.html) keeps its own sign-in. On a shared PC a cashier's
// PIN used to replace the owner's Friday session in the same browser,
// and Friday then treated the owner as staff (owner, 2026-11-22).
const STORAGE_KEY =
  typeof window !== "undefined" && window.location.pathname.startsWith("/pos") ? "friday.pos.session" : "friday.session";

export function loadSession(): Session | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}

export function saveSession(session: Session): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearSession(): void {
  localStorage.removeItem(STORAGE_KEY);
}
