import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "./api";
import { clearSession, loadSession, saveSession } from "./session";
import type { Session } from "./types";

const KERNEL_URL = import.meta.env.VITE_KERNEL_URL ?? "http://localhost:8080";

interface AuthResponse {
  token: string;
  org_id: string;
  role: Session["role"];
}

async function kernelPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${KERNEL_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    throw new ApiError(res.status, payload.error ?? res.statusText);
  }
  return (await res.json()) as T;
}

interface AuthContextValue {
  session: Session | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (orgName: string, email: string, password: string, fullName: string) => Promise<void>;
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

  const applyAuthResponse = useCallback((resp: AuthResponse, email: string) => {
    const next: Session = { token: resp.token, orgId: resp.org_id, role: resp.role, email };
    saveSession(next);
    setSession(next);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const resp = await kernelPost<AuthResponse>("/auth/login", { email, password });
      applyAuthResponse(resp, email);
    },
    [applyAuthResponse],
  );

  const register = useCallback(
    async (orgName: string, email: string, password: string, fullName: string) => {
      const resp = await kernelPost<AuthResponse>("/auth/register", {
        org_name: orgName,
        email,
        password,
        full_name: fullName,
      });
      applyAuthResponse(resp, email);
    },
    [applyAuthResponse],
  );

  const logout = useCallback(() => {
    clearSession();
    setSession(null);
  }, []);

  const value = useMemo(
    () => ({ session, ready, login, register, logout }),
    [session, ready, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
