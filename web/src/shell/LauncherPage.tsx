import { useEffect, useState } from "react";
import { fetchCatalog } from "../lib/catalog";
import type { AppCatalogEntry } from "../lib/types";
import { ApiError } from "../lib/api";
import { AppTile } from "../ui/AppTile";

export function LauncherPage() {
  const [apps, setApps] = useState<AppCatalogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchCatalog()
      .then(setApps)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load apps"));
  }, []);

  if (error) return <div className="page error-banner">{error}</div>;
  if (!apps) return <div className="page spinner">Loading...</div>;

  const installed = apps.filter((a) => a.installed);
  const hasInvoicing = installed.some((a) => a.name === "invoicing");

  if (installed.length === 0) {
    return (
      <div className="page">
        <div className="empty-state">
          No apps installed yet. Visit the <a href="/apps">Apps catalog</a> to enable one.
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Friday</h1>
      </div>
      <div className="app-grid">
        {installed.map((a) => (
          <AppTile key={a.name} to={`/${a.name}`} icon={a.icon} label={a.label} description={a.description} />
        ))}
        {hasInvoicing ? (
          <AppTile to="/pos" icon="receipt" label="Point of Sale" description="Ring up a sale at the register." />
        ) : null}
      </div>
    </div>
  );
}
