import { useEffect, useMemo, useState } from "react";
import { fetchCatalog } from "../lib/catalog";
import { listRecords } from "../lib/resourceApi";
import type { AppCatalogEntry, RecordRow } from "../lib/types";
import { ApiError } from "../lib/api";
import { Gauge } from "../ui/Gauge";
import { StatCard } from "../ui/StatCard";
import { AppTile } from "../ui/AppTile";
import { Icon, type IconName } from "../ui/Icon";

function money(cents: number): string {
  return `$${Math.round(cents / 100).toLocaleString()}`;
}

function timeAgo(iso: unknown): string {
  const ms = Date.now() - new Date(String(iso)).getTime();
  const mins = Math.max(0, Math.round(ms / 60000));
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function dotsRow(filled: number, total = 5, tone?: "danger") {
  return (
    <div className="stat-dots">
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={`stat-dot${i < filled ? " filled" : ""}`}
          style={i < filled && tone === "danger" ? { background: "var(--danger)" } : undefined}
        />
      ))}
    </div>
  );
}

interface ActivityItem {
  id: string;
  icon: IconName;
  title: string;
  at: unknown;
}

/** The home screen: a hero win-rate gauge, a stat-card grid pulled from
 * whatever apps this org has installed, a dark "recent activity" band,
 * and the app launcher grid underneath -- same visual system as the
 * reference dashboard (gauge + icon-chip/arrow-button cards + a
 * contrast band), built from Friday's real data instead of fake credit
 * content. Degrades per-card when an app isn't installed, same as the
 * old launcher did for the whole page. */
export function DashboardPage() {
  const [apps, setApps] = useState<AppCatalogEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opportunities, setOpportunities] = useState<RecordRow[] | null>(null);
  const [invoices, setInvoices] = useState<RecordRow[] | null>(null);
  const [tasks, setTasks] = useState<RecordRow[] | null>(null);
  const [tickets, setTickets] = useState<RecordRow[] | null>(null);
  const [products, setProducts] = useState<RecordRow[] | null>(null);

  useEffect(() => {
    fetchCatalog()
      .then(setApps)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load apps"));
  }, []);

  const installed = useMemo(
    () => new Set((apps ?? []).filter((a) => a.installed).map((a) => a.name)),
    [apps],
  );

  useEffect(() => {
    if (!apps) return;
    if (installed.has("crm")) {
      listRecords("crm", "opportunity").then(setOpportunities).catch(() => setOpportunities([]));
    }
    if (installed.has("invoicing")) {
      listRecords("invoicing", "invoice").then(setInvoices).catch(() => setInvoices([]));
    }
    if (installed.has("projects")) {
      listRecords("projects", "task").then(setTasks).catch(() => setTasks([]));
      listRecords("projects", "ticket").then(setTickets).catch(() => setTickets([]));
    }
    if (installed.has("inventory")) {
      listRecords("inventory", "product").then(setProducts).catch(() => setProducts([]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apps]);

  const crmStats = useMemo(() => {
    const rows = opportunities ?? [];
    const open = rows.filter((o) => o.stage !== "won" && o.stage !== "lost");
    const won = rows.filter((o) => o.stage === "won").length;
    const lost = rows.filter((o) => o.stage === "lost").length;
    const pipelineValue = rows
      .filter((o) => o.stage !== "lost")
      .reduce((sum, o) => sum + (Number(o.value_cents) || 0), 0);
    const closed = won + lost;
    const winRate = closed === 0 ? 0 : (won / closed) * 100;
    const tier = closed === 0 ? "No closed deals yet" : winRate >= 70 ? "Excellent" : winRate >= 40 ? "Good" : "Needs attention";
    return { openCount: open.length, pipelineValue, won, lost, winRate, tier };
  }, [opportunities]);

  const invoicingStats = useMemo(() => {
    const rows = invoices ?? [];
    const unpaid = rows.filter((i) => i.status !== "paid" && i.status !== "void");
    const outstanding = unpaid.reduce((sum, i) => sum + (Number(i.balance_cents) || 0), 0);
    const collected = rows.reduce((sum, i) => sum + (Number(i.paid_cents) || 0), 0);
    return { unpaidCount: unpaid.length, outstanding, collected, total: rows.length };
  }, [invoices]);

  const taskStats = useMemo(() => {
    const rows = tasks ?? [];
    const open = rows.filter((t) => t.status !== "done").length;
    const done = rows.length - open;
    const filled = rows.length === 0 ? 0 : Math.round((done / rows.length) * 5);
    return { open, done, total: rows.length, filled };
  }, [tasks]);

  const ticketStats = useMemo(() => {
    const rows = tickets ?? [];
    const open = rows.filter((t) => t.status === "open" || t.status === "pending").length;
    const resolved = rows.filter((t) => t.status === "resolved" || t.status === "closed").length;
    return { open, resolved };
  }, [tickets]);

  const stockStats = useMemo(() => {
    const rows = (products ?? []).filter((p) => p.track_inventory);
    const low = rows.filter((p) => Number(p.reorder_point) > 0 && Number(p.on_hand_qty) <= Number(p.reorder_point));
    const filled = rows.length === 0 ? 0 : Math.min(5, low.length === 0 ? 0 : Math.max(1, Math.ceil((low.length / rows.length) * 5)));
    return { lowCount: low.length, trackedCount: rows.length, filled };
  }, [products]);

  const activity = useMemo<ActivityItem[]>(() => {
    const items: ActivityItem[] = [];
    for (const o of opportunities ?? []) {
      items.push({ id: `opp-${o.id}`, icon: "target", title: `${o.contact_name} — ${o.stage}`, at: o.updated_at ?? o.created_at });
    }
    for (const i of invoices ?? []) {
      items.push({ id: `inv-${i.id}`, icon: "receipt", title: `Invoice ${i.number} — ${i.status}`, at: i.created_at });
    }
    for (const t of tasks ?? []) {
      items.push({ id: `task-${t.id}`, icon: "kanban", title: `${t.title} — ${t.status}`, at: t.created_at });
    }
    return items
      .filter((it) => it.at)
      .sort((a, b) => new Date(String(b.at)).getTime() - new Date(String(a.at)).getTime())
      .slice(0, 8);
  }, [opportunities, invoices, tasks]);

  if (error) return <div className="page error-banner">{error}</div>;
  if (!apps) return <div className="page spinner">Loading...</div>;

  const installedApps = apps.filter((a) => a.installed);

  if (installedApps.length === 0) {
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

      <div className="app-grid" style={{ marginBottom: 32 }}>
        {installedApps.map((a) => (
          <AppTile key={a.name} to={`/${a.name}`} icon={a.icon} label={a.label} />
        ))}
        {installed.has("invoicing") ? <AppTile to="/pos" icon="receipt" label="Point of Sale" /> : null}
      </div>

      <div className="dashboard-section-title">Overview</div>
      <div className="dashboard-layout" style={{ marginBottom: 24 }}>
        <div className="dashboard-hero">
          {installed.has("crm") ? (
            <>
              <Gauge percent={crmStats.winRate} />
              <div className="gauge-wrap">
                <span className="gauge-trend">
                  {crmStats.won} won · {crmStats.lost} lost
                </span>
                <span className="gauge-value">{Math.round(crmStats.winRate)}%</span>
                <span className="gauge-sub">Win rate · {crmStats.tier}</span>
              </div>
            </>
          ) : (
            <div className="empty-state">Install CRM to see pipeline health here.</div>
          )}
        </div>

        <div className="dashboard-grid">
          {installed.has("crm") ? (
            <StatCard
              to="/crm/opportunity"
              icon="target"
              label="Pipeline value"
              value={money(crmStats.pipelineValue)}
              featured
              footer={<span className="field-label">{crmStats.openCount} open opportunities</span>}
            />
          ) : null}
          {installed.has("invoicing") ? (
            <StatCard
              to="/invoicing/invoice"
              icon="receipt"
              label="Outstanding"
              value={money(invoicingStats.outstanding)}
              footer={<span className="field-label">{invoicingStats.unpaidCount} unpaid invoices</span>}
            />
          ) : null}
          {installed.has("invoicing") ? (
            <StatCard
              to="/invoicing/invoice"
              icon="trend-up"
              label="Collected"
              value={money(invoicingStats.collected)}
              footer={<span className="field-label">{invoicingStats.total} invoices total</span>}
            />
          ) : null}
          {installed.has("projects") ? (
            <StatCard
              to="/projects/task"
              icon="kanban"
              label="Open tasks"
              value={String(taskStats.open)}
              footer={dotsRow(taskStats.filled)}
            />
          ) : null}
          {installed.has("projects") ? (
            <StatCard
              to="/projects/ticket"
              icon="ticket"
              label="Open tickets"
              value={String(ticketStats.open)}
              footer={<span className="field-label">{ticketStats.resolved} resolved</span>}
            />
          ) : null}
          {installed.has("inventory") ? (
            <StatCard
              to="/inventory/product"
              icon="box"
              label="Low stock"
              value={String(stockStats.lowCount)}
              footer={dotsRow(stockStats.filled, 5, "danger")}
            />
          ) : null}
        </div>
      </div>

      <div className="band-ink">
        <div className="dashboard-section-title">Recent activity</div>
        {activity.length === 0 ? (
          <div className="field-label">Nothing yet.</div>
        ) : (
          activity.map((item) => (
            <div className="activity-row" key={item.id}>
              <div className="activity-row-main">
                <span className="activity-row-icon">
                  <Icon name={item.icon} size={14} />
                </span>
                <span>{item.title}</span>
              </div>
              <span className="activity-row-time">{timeAgo(item.at)}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
