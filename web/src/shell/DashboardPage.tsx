import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchCatalog } from "../lib/catalog";
import type { AppCatalogEntry } from "../lib/types";
import { ApiError } from "../lib/api";
import { useMyPermissions } from "../lib/permissions";
import { AppTile, APP_ICONS } from "../ui/AppTile";

// An app's tile shows when the person can open it at all (plan 12.7).
const OPEN_RULES: Record<string, string[]> = {
  crm: ["crm.read"],
  invoicing: ["invoices.read", "sales.read"],
  inventory: ["stock.read"],
  accounting: ["books.read"],
  web3: ["books.read"],
  fleets: ["deliveries.read"],
  minions: ["staff.read", "claims.submit"],
};
// Where each app opens; the rest open at /<name>.
const HOME_OF: Record<string, string> = { web3: "/web3/treasury", accounting: "/accounting/reports", minions: "/people" };
// Daily-work apps first, back-office after; unknown apps go last by name.
const APP_ORDER = ["crm", "invoicing", "inventory", "projects", "minions", "accounting", "fleets", "web3"];
const rank = (name: string) => (APP_ORDER.indexOf(name) + 1 || APP_ORDER.length + 1);

/** Home (owner, plan 17): only the apps, as large tiles. The overview and
 * recent activity live in My Store. */
export function DashboardPage() {
  const [apps, setApps] = useState<AppCatalogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const me = useMyPermissions();

  useEffect(() => {
    fetchCatalog()
      .then(setApps)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load apps"));
  }, []);

  if (error) return <div className="page error-banner">{error}</div>;
  if (!apps) return <div className="page spinner">Loading...</div>;

  const can = (...rules: string[]) => !me || rules.some((r) => !!me.rules[r]);
  const shown = apps
    .filter((a) => a.installed && (!OPEN_RULES[a.name] || can(...OPEN_RULES[a.name])))
    .sort((a, b) => rank(a.name) - rank(b.name) || a.label.localeCompare(b.label));
  const sells = shown.some((a) => a.name === "invoicing") && can("invoices.read", "pos.sell");

  return (
    <div className="page home">
      <h1 className="page-title">Your apps</h1>
      {shown.length === 0 ? (
        <div className="empty-state">
          No apps yet. Add one from <Link to="/apps">Apps & integrations</Link>.
        </div>
      ) : (
        <div className="app-grid">
          <AppTile to="/store" app="store" label="My Store" />
          {shown.map((a) => (
            <AppTile key={a.name} to={HOME_OF[a.name] ?? `/${a.name}`} app={a.name} label={APP_ICONS[a.name]?.label ?? a.label} />
          ))}
          {sells ? <AppTile to="/pos.html" app="pos" label="Point of Sale" external /> : null}
          <AppTile to="/apps" app="more" label="Add apps" />
        </div>
      )}
    </div>
  );
}
