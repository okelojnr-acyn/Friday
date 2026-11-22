import { useEffect, useState } from "react";
import { api } from "./api";

/** What the signed-in person may do (kernel GET /orgs/me/permissions,
 * from the same rules every app enforces; plan section 12). The screens
 * use it to show only what someone can use; the apps still check. */
export interface MyPermissions {
  role: string;
  perms: string[];
  /** Location ids, or ["*"] for all. */
  locations: string[];
  team_size: number;
  staff_id: string | null;
  /** rule -> scope ("all" | "loc" | "team" | "own"); missing = no. */
  rules: Record<string, string>;
}

let cached: Promise<MyPermissions> | null = null;

export function fetchMyPermissions(): Promise<MyPermissions> {
  cached ??= api.get<MyPermissions>("/orgs/me/permissions").catch((err) => {
    cached = null;
    throw err;
  });
  return cached;
}

/** null while loading, or when an older kernel can't say (then the
 * screens show what they always showed). */
export function useMyPermissions(): MyPermissions | null {
  const [me, setMe] = useState<MyPermissions | null>(null);
  useEffect(() => {
    fetchMyPermissions()
      .then(setMe)
      .catch(() => {});
  }, []);
  return me;
}
