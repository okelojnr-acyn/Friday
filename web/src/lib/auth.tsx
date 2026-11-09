import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import {
  startAuthentication,
  startRegistration,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
} from "@simplewebauthn/browser";
import { ApiError } from "./api";
import { clearSession, loadSession, saveSession } from "./session";
import type { Session } from "./types";

const KERNEL_URL = import.meta.env.VITE_KERNEL_URL ?? "http://localhost:8080";

interface AuthResponse {
  token: string;
  org_id: string;
  role: Session["role"];
  email: string;
}

async function kernelFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${KERNEL_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers as Record<string, string> | undefined) },
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new ApiError(res.status, payload.error ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const kernelPost = <T,>(path: string, body?: unknown, headers?: Record<string, string>) =>
  kernelFetch<T>(path, {
    method: "POST",
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

interface AuthContextValue {
  session: Session | null;
  ready: boolean;
  /** Starts a signup: stores the pending org/profile and emails a
   * verification code. No account exists yet -- call verifyCode next. */
  startSignup: (orgName: string, email: string, fullName: string) => Promise<void>;
  /** Emails a login code to an existing account. Same response whether
   * or not the email has one -- see kernel/internal/auth/handlers.go's
   * OtpRequest. */
  requestLoginCode: (email: string) => Promise<void>;
  /** Completes either flow: a pending signup, or a fallback login --
   * the server figures out which, the caller doesn't need to track it. */
  verifyCode: (email: string, code: string) => Promise<void>;
  /** Completes an invite someone else sent via Settings > Members --
   * joins their org with the role they were invited at, rather than
   * creating a brand new org (see kernel/internal/auth/invites.go's
   * AcceptInvite). */
  acceptInvite: (email: string, code: string, fullName: string) => Promise<void>;
  /** Usernameless passkey login -- the browser's own passkey picker
   * decides which account, no email prompt at all. */
  loginWithPasskey: () => Promise<void>;
  /** Adds a passkey to the *current* session's account (call right
   * after signup, or later from a settings screen). `platformOnly`
   * constrains the registration to a real fingerprint/Face ID (not a
   * security key) -- used by POS clock-in registration
   * (web/src/apps/pos/PosClockIn.tsx); omit for the general "add a
   * passkey to my account" flow, which stays unconstrained. */
  addPasskey: (opts?: { platformOnly?: boolean }) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const stored = loadSession();
    if (!stored) {
      setReady(true);
      return;
    }
    // Validate the stored token still works (it may have expired since
    // the last visit) before trusting it.
    fetch(`${KERNEL_URL}/auth/me`, { headers: { Authorization: `Bearer ${stored.token}` } })
      .then((res) => {
        if (res.ok) {
          setSession(stored);
        } else {
          clearSession();
        }
      })
      .catch(() => setSession(stored)) // network hiccup: don't log the user out for it
      .finally(() => setReady(true));
  }, []);

  const applyAuthResponse = useCallback((resp: AuthResponse) => {
    const next: Session = { token: resp.token, orgId: resp.org_id, role: resp.role, email: resp.email };
    saveSession(next);
    setSession(next);
  }, []);

  const startSignup = useCallback(async (orgName: string, email: string, fullName: string) => {
    await kernelPost("/auth/register", { org_name: orgName, email, full_name: fullName });
  }, []);

  const requestLoginCode = useCallback(async (email: string) => {
    await kernelPost("/auth/otp/request", { email });
  }, []);

  const verifyCode = useCallback(
    async (email: string, code: string) => {
      const resp = await kernelPost<AuthResponse>("/auth/otp/verify", { email, code });
      applyAuthResponse(resp);
    },
    [applyAuthResponse],
  );

  const acceptInvite = useCallback(
    async (email: string, code: string, fullName: string) => {
      const resp = await kernelPost<AuthResponse>("/auth/invites/accept", { email, code, full_name: fullName });
      applyAuthResponse(resp);
    },
    [applyAuthResponse],
  );

  const loginWithPasskey = useCallback(async () => {
    const { session_id, publicKey } = await kernelPost<{
      session_id: string;
      publicKey: PublicKeyCredentialRequestOptionsJSON;
    }>("/auth/passkey/login-options");
    const responseJSON = await startAuthentication({ optionsJSON: publicKey });
    const resp = await kernelFetch<AuthResponse>(`/auth/passkey/login-verify?session_id=${session_id}`, {
      method: "POST",
      body: JSON.stringify(responseJSON),
    });
    applyAuthResponse(resp);
  }, [applyAuthResponse]);

  const addPasskey = useCallback(
    async (opts?: { platformOnly?: boolean }) => {
      if (!session) throw new Error("addPasskey requires an active session");
      const authHeader = { Authorization: `Bearer ${session.token}` };
      const query = opts?.platformOnly ? "?purpose=pos" : "";
      const { session_id, publicKey } = await kernelPost<{
        session_id: string;
        publicKey: PublicKeyCredentialCreationOptionsJSON;
      }>(`/auth/passkey/register-options${query}`, undefined, authHeader);
      const responseJSON = await startRegistration({ optionsJSON: publicKey });
      await kernelFetch(`/auth/passkey/register-verify?session_id=${session_id}`, {
        method: "POST",
        headers: authHeader,
        body: JSON.stringify(responseJSON),
      });
    },
    [session],
  );

  const logout = useCallback(() => {
    clearSession();
    setSession(null);
  }, []);

  const value = useMemo(
    () => ({
      session,
      ready,
      startSignup,
      requestLoginCode,
      verifyCode,
      acceptInvite,
      loginWithPasskey,
      addPasskey,
      logout,
    }),
    [session, ready, startSignup, requestLoginCode, verifyCode, acceptInvite, loginWithPasskey, addPasskey, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
