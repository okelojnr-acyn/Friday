import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { useAuth } from "./auth";

/** Organisation settings every screen needs (kernel GET /orgs/settings):
 * the currency money is shown in, and how tax works at the till. */
export interface TaxRate {
  code: string;
  name: string;
  rate_bp: number;
}

/** Business settings > Tax (kernel core.orgs.tax_profile). The till's
 * tax_rate_bp follows from it: the default rate when VAT-registered. */
export interface TaxProfile {
  vat_registered: boolean;
  tax_pin: string;
  default_code: string;
  rates: TaxRate[];
  receipt_show_pin: boolean;
  receipt_show_breakdown: boolean;
  receipt_footer: string;
}

export interface OrgSettings {
  name: string;
  currency: string;
  tax_rate_bp: number;
  prices_include_tax: boolean;
  /** Missing on a kernel older than the Tax section. */
  tax?: TaxProfile;
}

// Until the org's own settings arrive, money shows in the default the
// kernel gives new organisations.
const DEFAULTS: OrgSettings = { name: "", currency: "KES", tax_rate_bp: 1600, prices_include_tax: true };

// formatMoney is called from plain functions (list cells, CSV), not only
// components, so the current settings also live here.
let current: OrgSettings = DEFAULTS;

export function currentOrgSettings(): OrgSettings {
  return current;
}

const formatters = new Map<string, Intl.NumberFormat>();

function formatter(currency: string, whole: boolean): Intl.NumberFormat {
  const key = `${currency}:${whole}`;
  let f = formatters.get(key);
  if (!f) {
    try {
      f = new Intl.NumberFormat("en-KE", {
        style: "currency",
        currency,
        minimumFractionDigits: whole ? 0 : 2,
        maximumFractionDigits: whole ? 0 : 2,
      });
    } catch {
      f = new Intl.NumberFormat("en-KE", { minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2 });
    }
    formatters.set(key, f);
  }
  return f;
}

/** "Ksh 1,250.00" in the org's currency (or `currency` when a document
 * carries its own). `whole` drops the cents, for headline numbers. */
export function formatMoney(cents: number, opts?: { currency?: string; whole?: boolean }): string {
  const currency = (opts?.currency || current.currency || "KES").toUpperCase();
  return formatter(currency, !!opts?.whole).format((Number(cents) || 0) / 100);
}

const Ctx = createContext<OrgSettings>(DEFAULTS);

export function OrgSettingsProvider({ children }: { children: ReactNode }) {
  const { session } = useAuth();
  const [settings, setSettings] = useState<OrgSettings>(current);

  useEffect(() => {
    if (!session) return;
    api
      .get<OrgSettings>("/orgs/settings")
      .then((s) => {
        current = s;
        setSettings(s);
      })
      .catch(() => {
        // An older kernel without settings: keep the defaults.
      });
  }, [session?.orgId, session?.token]);

  return <Ctx.Provider value={settings}>{children}</Ctx.Provider>;
}

export function useOrgSettings(): OrgSettings {
  return useContext(Ctx);
}

/** Saves settings (owners and admins) and updates every screen. */
export async function saveOrgSettings(patch: Partial<Omit<OrgSettings, "name">>): Promise<OrgSettings> {
  const s = await api.put<OrgSettings>("/orgs/settings", patch);
  current = s;
  return s;
}
