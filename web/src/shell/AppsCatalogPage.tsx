import { useEffect, useState } from "react";
import { fetchCatalog, installApp, uninstallApp } from "../lib/catalog";
import type { AppCatalogEntry } from "../lib/types";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Button } from "../ui/Button";
import { Badge } from "../ui/Badge";

export function AppsCatalogPage() {
  const { session } = useAuth();
  const [apps, setApps] = useState<AppCatalogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  const canManage = session?.role === "owner" || session?.role === "admin";

  function load() {
    fetchCatalog()
      .then(setApps)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load apps"));
  }

  useEffect(load, []);

  async function toggle(app: AppCatalogEntry) {
    setPending(app.name);
    setError(null);
    try {
      if (app.installed) {
        await uninstallApp(app.name);
      } else {
        await installApp(app.name);
      }
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update app");
    } finally {
      setPending(null);
    }
  }

  if (!apps) return <div className="page spinner">Loading...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Apps</h1>
      </div>
      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>App</th>
              <th>Category</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {apps.map((app) => (
              <tr key={app.name} style={{ cursor: "default" }}>
                <td>
                  <div style={{ fontWeight: 500 }}>{app.label}</div>
                  <div className="field-label">{app.description}</div>
                </td>
                <td>{app.category}</td>
                <td>
                  <Badge tone={app.installed ? "success" : "neutral"}>
                    {app.installed ? "Installed" : "Not installed"}
                  </Badge>
                </td>
                <td style={{ textAlign: "right" }}>
                  {canManage ? (
                    <Button
                      size="sm"
                      variant={app.installed ? "secondary" : "primary"}
                      disabled={pending === app.name}
                      onClick={() => toggle(app)}
                    >
                      {app.installed ? "Uninstall" : "Install"}
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
