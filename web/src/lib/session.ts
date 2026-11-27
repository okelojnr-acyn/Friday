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

// A sign-in just made on this page (passkey or code) already proves who's
// at the till; the clock-in takes it instead of asking for the finger a
// second time (owner, 27 Nov). Two minutes, this tab only.
const FRESH_KEY = "friday.signedInAt";
const FRESH_MS = 2 * 60_000;

export function markSignedInNow(): void {
  // The till's own sign-in only: a Friday sign-in in this tab says nothing
  // about whose till session is stored.
  if (STORAGE_KEY !== "friday.pos.session") return;
  try {
    sessionStorage.setItem(FRESH_KEY, String(Date.now()));
  } catch {
    /* private mode: the till asks again, as before */
  }
}

export function takeFreshSignIn(now = Date.now()): boolean {
  try {
    const at = Number(sessionStorage.getItem(FRESH_KEY));
    sessionStorage.removeItem(FRESH_KEY);
    return at > 0 && now - at < FRESH_MS;
  } catch {
    return false;
  }
}
