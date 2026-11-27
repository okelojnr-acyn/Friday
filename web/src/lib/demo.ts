import { useEffect, useState } from "react";
import { KERNEL_URL } from "./runtimeConfig";

/** The demo Friday's ways in ("owner", "cashier"), or null on a real
 * Friday (its kernel answers 404). Asked once per page load. */
let asked: Promise<string[] | null> | null = null;

export function demoRoles(): Promise<string[] | null> {
  asked ??= fetch(`${KERNEL_URL}/auth/demo`)
    .then((r) => (r.ok ? r.json() : null))
    .then((d: { roles?: string[] } | null) => d?.roles ?? null)
    .catch(() => null);
  return asked;
}

export function useDemoRoles(): string[] | null {
  const [roles, setRoles] = useState<string[] | null>(null);
  useEffect(() => {
    let live = true;
    demoRoles().then((r) => live && setRoles(r));
    return () => {
      live = false;
    };
  }, []);
  return roles;
}
