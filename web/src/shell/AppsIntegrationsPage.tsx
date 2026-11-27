import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { fetchCatalog, installApp, uninstallApp } from "../lib/catalog";
import { listIntegrations } from "../lib/integrations";
import { KERNEL_URL } from "../lib/runtimeConfig";
import type { AppCatalogEntry } from "../lib/types";
import { APP_ICONS } from "../ui/AppTile";
import { AppMark } from "../ui/AppMark";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Icon, type IconName } from "../ui/Icon";
import { Modal } from "../ui/Modal";
import { GussAccessCard } from "./GussAccessCard";
import { PROVIDERS, ProviderEditor, type ProviderDescriptor } from "./integrations";

/** One card on the page: a Friday app or an integration. */
type Item =
  | { kind: "app"; key: string; label: string; group: string; enabled: boolean; app: AppCatalogEntry }
  | { kind: "integration"; key: string; label: string; group: string; enabled: boolean; provider: ProviderDescriptor };

const APPS_GROUP = "Friday apps";
const GROUPS: [string, IconName][] = [
  [APPS_GROUP, "apps"],
  ["Get paid", "credit-card"],
  ["Talk to customers", "message-circle"],
  ["Schedule", "calendar"],
  ["Web3", "chain"],
  ["Data", "database"],
];

function ItemIcon({ item }: { item: Item }) {
  if (item.kind === "integration" && item.provider.logo) {
    return (
      <span className="hub-icon">
        <img src={item.provider.logo} alt="" width={26} height={26} />
      </span>
    );
  }
  const a = item.kind === "app" ? APP_ICONS[item.key] : undefined;
  const icon = a?.icon ?? (item.kind === "integration" ? item.provider.icon : "app-window");
  return (
    <span className="hub-icon" style={{ color: a?.color ?? "var(--accent)" }}>
      {a && item.kind === "app" ? <AppMark app={item.key} size={24} /> : <Icon name={icon} size={22} />}
    </span>
  );
}

/** Apps & integrations (owner's design, 2026-11-21): Friday's apps and
 * the outside services it connects to on one page. A left rail (Home,
 * All, Enabled, sections), search, and cards; a card opens Install /
 * Uninstall for an app or the settings for an integration. Replaces the
 * old Apps table and Settings > Integrations. */
export function AppsIntegrationsPage() {
  const { session } = useAuth();
  const canManage = session?.role === "owner" || session?.role === "admin";
  const [params, setParams] = useSearchParams();
  const [apps, setApps] = useState<AppCatalogEntry[] | null>(null);
  const [connected, setConnected] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [query, setQuery] = useState("");
  const view = params.get("view") ?? "home";
  const open = params.get("item");

  function load() {
    fetchCatalog()
      .then(setApps)
      .catch((err) => {
        setApps([]);
        setError(err instanceof ApiError ? err.message : "Could not load apps");
      });
    listIntegrations()
      .then((rows) => setConnected(new Set(rows.map((r) => r.provider))))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load integrations"));
  }
  useEffect(load, []);

  const items: Item[] = useMemo(
    () => [
      ...(apps ?? []).map(
        (app): Item => ({ kind: "app", key: app.name, label: APP_ICONS[app.name]?.label ?? app.label, group: APPS_GROUP, enabled: app.installed, app }),
      ),
      ...PROVIDERS.map(
        (p): Item => ({
          kind: "integration",
          key: p.key,
          label: p.label,
          group: p.group,
          enabled: connected.has(p.key),
          provider: p,
        }),
      ),
    ],
    [apps, connected],
  );

  function go(next: Record<string, string | null>) {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) {
      if (v === null) p.delete(k);
      else p.set(k, v);
    }
    setParams(p, { replace: true });
  }

  const q = query.trim().toLowerCase();
  const shown = items.filter(
    (i) =>
      (!q || i.label.toLowerCase().includes(q) || i.group.toLowerCase().includes(q)) &&
      (view !== "enabled" || i.enabled) &&
      (view === "home" || view === "all" || view === "enabled" || i.group === view),
  );
  const sections: [string, Item[]][] =
    view === "all" || view === "enabled" || q
      ? [[view === "enabled" ? "Enabled" : q ? "Results" : "All", [...shown].sort((a, b) => a.label.localeCompare(b.label))]]
      : GROUPS.map(([g]) => [g, shown.filter((i) => i.group === g)] as [string, Item[]]).filter(([, l]) => l.length);
  const enabledCount = items.filter((i) => i.enabled).length;
  const current = items.find((i) => i.key === open) ?? null;

  async function toggleApp(app: AppCatalogEntry) {
    setPending(true);
    setError(null);
    try {
      await (app.installed ? uninstallApp(app.name) : installApp(app.name));
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not update the app");
    } finally {
      setPending(false);
    }
  }

  // Where Google's consent screen sends the browser back.
  const google = params.get("google_calendar");

  const navButton = (id: string, label: string, icon?: IconName, count?: number) => (
    <button
      key={id}
      type="button"
      className={`hub-nav-item${view === id ? " active" : ""}`}
      aria-current={view === id ? "page" : undefined}
      onClick={() => go({ view: id === "home" ? null : id })}
    >
      {icon ? <Icon name={icon} size={16} /> : null}
      <span>{label}</span>
      {count !== undefined ? <span className="hub-nav-count">{count}</span> : null}
    </button>
  );

  return (
    <div className="page">
      <div className="hub">
        <nav className="hub-nav" aria-label="Apps and integrations">
          {navButton("home", "Home")}
          {navButton("all", "All")}
          {navButton("enabled", "Enabled", undefined, enabledCount)}
          <hr />
          {GROUPS.map(([g, icon]) => navButton(g, g, icon))}
        </nav>
        <div className="hub-main">
          <div className="hub-head">
            <h1 className="page-title" style={{ margin: 0 }}>
              Apps & integrations
            </h1>
            <label className="hub-search">
              <Icon name="search" size={16} />
              <input
                type="search"
                placeholder="Search apps and integrations"
                aria-label="Search apps and integrations"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
          </div>
          {google === "connected" ? <Badge tone="success">Google Calendar connected</Badge> : null}
          {google === "error" ? (
            <div className="error-banner">Could not connect Google Calendar. Check the client ID and secret and try again.</div>
          ) : null}
          {error ? <div className="error-banner">{error}</div> : null}
          {apps === null ? <div className="spinner">Loading...</div> : null}
          {apps !== null && sections.length === 0 ? <p className="field-label">Nothing matches.</p> : null}
          {sections.map(([title, list]) => (
            <section key={title} className="hub-section">
              <h2>
                {view === "home" && !q ? (
                  <button type="button" onClick={() => go({ view: title })}>
                    {title}{" "}
                    <span style={{ display: "inline-flex", transform: "rotate(-90deg)" }}>
                      <Icon name="chevron-down" size={14} />
                    </span>
                  </button>
                ) : (
                  title
                )}
              </h2>
              <div className="hub-grid">
                {list.map((i) => (
                  <button key={`${i.kind}:${i.key}`} type="button" className="hub-card" onClick={() => go({ item: i.key })}>
                    <ItemIcon item={i} />
                    <span className="hub-card-label">{i.label}</span>
                    {i.enabled ? <span className="hub-dot" title={i.kind === "app" ? "Installed" : "Connected"} /> : null}
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>

      {current ? (
        <Modal title={current.label} onClose={() => go({ item: null, google_calendar: null })}>
          <div style={{ display: "grid", gap: 14 }}>
            <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
              <ItemIcon item={current} />
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                <Badge tone={current.enabled ? "success" : "neutral"}>
                  {current.kind === "app"
                    ? current.enabled
                      ? "Installed"
                      : "Not installed"
                    : current.enabled
                      ? "Connected"
                      : "Not connected"}
                </Badge>
                {current.kind === "integration" && !current.provider.codeReady ? <Badge tone="neutral">Coming soon</Badge> : null}
              </div>
            </div>
            {current.kind === "app" ? (
              <>
                <p style={{ margin: 0 }}>{current.app.description}</p>
                {canManage ? (
                  <div>
                    <Button
                      variant={current.enabled ? "danger" : "primary"}
                      disabled={pending}
                      onClick={() => toggleApp(current.app)}
                    >
                      {pending ? "Working…" : current.enabled ? "Uninstall" : "Install"}
                    </Button>
                  </div>
                ) : (
                  <p className="field-label">Only owners and admins install apps.</p>
                )}
              </>
            ) : (
              <>
                <p style={{ margin: 0 }}>{current.provider.blurb}</p>
                {current.provider.webhook === "paste" ? (
                  <p style={{ margin: 0 }}>
                    Webhook URL: <code style={{ userSelect: "all", wordBreak: "break-all" }}>{webhookUrl(current.key)}</code>
                  </p>
                ) : current.provider.webhook === "automatic" ? (
                  <p style={{ margin: 0 }}>Friday gives {current.provider.label} its webhook address itself; nothing to paste.</p>
                ) : null}
                <ProviderEditor
                  key={current.key}
                  provider={current.provider}
                  connected={current.enabled}
                  canManage={canManage}
                  onChanged={load}
                />
                {current.key === "guss" && current.enabled ? <GussAccessCard canManage={canManage} /> : null}
              </>
            )}
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

/** Where a payment provider sends its events: this Friday's own address,
 * on whatever domain it runs; the kernel passes them to invoicing. */
function webhookUrl(provider: string): string {
  return new URL(`${KERNEL_URL.replace(/\/$/, "")}/external/webhooks/${provider}`, window.location.origin).href;
}
