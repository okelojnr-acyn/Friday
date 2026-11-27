import { Link } from "react-router-dom";
import { useEffect, useMemo, useState } from "react";
import { fetchCatalog } from "../lib/catalog";
import { listRecords } from "../lib/resourceApi";
import type { AppCatalogEntry, RecordRow } from "../lib/types";
import { ApiError } from "../lib/api";
import { Gauge } from "../ui/Gauge";
import { StatCard } from "../ui/StatCard";
import { useMyPermissions } from "../lib/permissions";
import { Icon, type IconName } from "../ui/Icon";
import { formatMoney } from "../lib/orgSettings";

function money(cents: number): string {
  return formatMoney(cents, { whole: true });
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

/** My Store (owner, plan 17): the business at a glance (win rate, money
 * owed and collected, tasks, tickets, low stock) and recent activity,
 * moved off the home page, with the store's settings one click away.
 * Degrades per card when an app isn't installed. */
export function StorePage() {
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
  // Cards follow who-sees-what (plan 12.7): a card someone can't use isn't
  // shown as zero, it isn't shown. An older kernel can't say: show all.
  const me = useMyPermissions();
  const RULE_OF: Record<string, string> = { crm: "crm.read", invoicing: "invoices.read", inventory: "stock.read" };
  const can = (app: string) => installed.has(app) && (!me || !RULE_OF[app] || !!me.rules[RULE_OF[app]]);
  const scopeNote = !me
    ? ""
    : me.role === "branch_manager"
      ? "Showing your locations"
      : me.role === "team_leader"
        ? "Showing your team"
        : me.role === "viewer"
          ? "Read only"
          : "";

  useEffect(() => {
    if (!apps) return;
    if (can("crm")) {
      listRecords("crm", "opportunity").then(setOpportunities).catch(() => setOpportunities([]));
    }
    if (can("invoicing")) {
      listRecords("invoicing", "invoice").then(setInvoices).catch(() => setInvoices([]));
    }
    if (installed.has("projects")) {
      listRecords("projects", "task").then(setTasks).catch(() => setTasks([]));
      listRecords("projects", "ticket").then(setTickets).catch(() => setTickets([]));
    }
    if (can("inventory")) {
      listRecords("inventory", "product").then(setProducts).catch(() => setProducts([]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apps, me]);

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
    const unpaid = rows.filter((i) => i.status !== "paid" && i.status !== "void" && i.status !== "draft");
    const outstanding = unpaid.reduce((sum, i) => sum + (Number(i.balance_cents) || 0), 0);
    const collected = rows.reduce((sum, i) => sum + (Number(i.paid_cents) || 0), 0);
    const now = Date.now();
    const overdue = unpaid.filter((i) => i.due_at && new Date(String(i.due_at)).getTime() < now);
    const overdueTotal = overdue.reduce((sum, i) => sum + (Number(i.balance_cents) || 0), 0);
    return { unpaidCount: unpaid.length, outstanding, collected, total: rows.length, overdueCount: overdue.length, overdueTotal };
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
    const low = rows.filter((p) => Number(p.on_hand_qty) <= Math.max(0, Number(p.reorder_point) || 0));
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

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">My Store</h1>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          {scopeNote ? <span className="field-label">{scopeNote}</span> : null}
          <Link to="/settings/store" className="btn btn-secondary btn-sm btn-pill">
            Store settings
          </Link>
        </div>
      </div>

      <div className="dashboard-layout" style={{ marginBottom: 24 }}>
        <div className="dashboard-hero">
          {can("crm") ? (
            <>
              <Gauge percent={crmStats.winRate} empty={crmStats.won + crmStats.lost === 0} />
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
          {can("crm") ? (
            <StatCard
              to="/crm/opportunity"
              icon="target"
              label="Pipeline value"
              value={money(crmStats.pipelineValue)}
              featured
              footer={<span className="field-label">{crmStats.openCount} open opportunities</span>}
            />
          ) : null}
          {can("invoicing") ? (
            <StatCard
              to="/invoicing/invoice"
              icon="receipt"
              label="Outstanding"
              value={money(invoicingStats.outstanding)}
              footer={<span className="field-label">{invoicingStats.unpaidCount} unpaid invoices</span>}
            />
          ) : null}
          {can("invoicing") ? (
            <StatCard
              to="/invoicing/invoice"
              icon="trend-up"
              label="Collected"
              value={money(invoicingStats.collected)}
              footer={<span className="field-label">{invoicingStats.total} invoices total</span>}
            />
          ) : null}
          {can("invoicing") && invoicingStats.overdueCount > 0 ? (
            <StatCard
              to="/invoicing/invoice"
              icon="receipt"
              label="Overdue"
              value={money(invoicingStats.overdueTotal)}
              footer={<span className="field-label">{invoicingStats.overdueCount} past due</span>}
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
          {can("inventory") ? (
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
