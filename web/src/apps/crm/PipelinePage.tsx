import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { fetchSchema } from "../../lib/schema";
import { listRecords, updateRecord } from "../../lib/resourceApi";
import { ApiError } from "../../lib/api";
import type { RecordRow, ResourceSpec } from "../../lib/types";
import { Gauge } from "../../ui/Gauge";
import { StatCard } from "../../ui/StatCard";
import { Card } from "../../ui/Card";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { KanbanView } from "../../ui/resource/KanbanView";
import { FormView } from "../../ui/resource/FormView";

function money(cents: number): string {
  return `$${(cents / 100).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

/** CRM's one hand-written screen (same justification as Accounting's
 * ReportsPage and Web3's TreasuryPage -- see ARCHITECTURE.md): win
 * rate, pipeline value, average deal size, and a lost-reason breakdown
 * are aggregation reads the generic ResourceSpec renderer has no
 * concept of, not CRUD. The actual stage board below is the *same*
 * KanbanView every other kanban-enabled resource gets for free
 * (drag-and-drop between stages included) -- this page adds the
 * numbers above it, it doesn't reinvent the board. The raw list and
 * Activities are still reachable at /crm/opportunity and /crm/activity
 * through the normal schema-driven screens. */
export function PipelinePage() {
  const [schema, setSchema] = useState<ResourceSpec[] | null>(null);
  const [opportunities, setOpportunities] = useState<RecordRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<RecordRow | "new" | null>(null);

  function load() {
    Promise.all([fetchSchema("crm"), listRecords("crm", "opportunity")])
      .then(([s, rows]) => {
        setSchema(s);
        setOpportunities(rows);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the pipeline"));
  }

  useEffect(load, []);

  const spec = useMemo(() => schema?.find((s) => s.name === "opportunity") ?? null, [schema]);

  const stats = useMemo(() => {
    const rows = opportunities ?? [];
    const open = rows.filter((o) => o.stage !== "won" && o.stage !== "lost");
    const won = rows.filter((o) => o.stage === "won");
    const lost = rows.filter((o) => o.stage === "lost");
    const openValue = open.reduce((sum, o) => sum + (Number(o.value_cents) || 0), 0);
    const wonValue = won.reduce((sum, o) => sum + (Number(o.value_cents) || 0), 0);
    const closed = won.length + lost.length;
    const winRate = closed === 0 ? 0 : (won.length / closed) * 100;
    const avgDealSize = won.length === 0 ? 0 : Math.round(wonValue / won.length);

    const lostReasons = new Map<string, number>();
    for (const o of lost) {
      const reason = (o.lost_reason as string) || "No reason given";
      lostReasons.set(reason, (lostReasons.get(reason) ?? 0) + 1);
    }

    return {
      openCount: open.length,
      openValue,
      won,
      lost,
      winRate,
      avgDealSize,
      lostReasons: Array.from(lostReasons.entries()).sort((a, b) => b[1] - a[1]),
    };
  }, [opportunities]);

  if (error) return <div className="page error-banner">{error}</div>;
  if (!schema || !opportunities || !spec) return <div className="page spinner">Loading...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Pipeline</h1>
          <nav style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Link to="/crm/opportunity" className="btn btn-sm btn-pill btn-secondary">
              All Opportunities
            </Link>
            <Link to="/crm/activity" className="btn btn-sm btn-pill btn-secondary">
              Activities
            </Link>
          </nav>
        </div>
        <Button variant="primary" size="sm" className="btn-pill" onClick={() => setEditing("new")}>
          <Icon name="plus" size={14} /> New Opportunity
        </Button>
      </div>

      <div className="dashboard-layout" style={{ marginBottom: 24 }}>
        <div className="dashboard-hero">
          <Gauge percent={stats.winRate} />
          <div className="gauge-wrap">
            <span className="gauge-trend">
              {stats.won.length} won · {stats.lost.length} lost
            </span>
            <span className="gauge-value">{Math.round(stats.winRate)}%</span>
            <span className="gauge-sub">Win rate</span>
          </div>
        </div>

        <div className="dashboard-grid">
          <StatCard
            icon="target"
            label="Open pipeline value"
            value={money(stats.openValue)}
            featured
            footer={<span className="field-label">{stats.openCount} open opportunities</span>}
          />
          <StatCard
            icon="trend-up"
            label="Average deal size"
            value={money(stats.avgDealSize)}
            footer={<span className="field-label">across {stats.won.length} won deals</span>}
          />
          <StatCard
            icon="receipt"
            label="Won value"
            value={money(stats.won.reduce((sum, o) => sum + (Number(o.value_cents) || 0), 0))}
            footer={<span className="field-label">all time</span>}
          />
        </div>
      </div>

      {stats.lostReasons.length > 0 ? (
        <Card style={{ marginBottom: 24 }}>
          <div className="field-label" style={{ marginBottom: 8 }}>
            Why deals are lost
          </div>
          {stats.lostReasons.map(([reason, count]) => (
            <div className="pos-totals-row" key={reason}>
              <span>{reason}</span>
              <span>{count}</span>
            </div>
          ))}
        </Card>
      ) : null}

      <KanbanView
        spec={spec}
        records={opportunities}
        onCardClick={setEditing}
        onMove={async (record, newStage) => {
          const prev = opportunities;
          setOpportunities(opportunities.map((o) => (o.id === record.id ? { ...o, stage: newStage } : o)));
          try {
            await updateRecord("crm", "opportunity", record.id, { stage: newStage });
          } catch (err) {
            setOpportunities(prev);
            setError(err instanceof ApiError ? err.message : "Could not move this opportunity");
          }
        }}
      />

      {editing ? (
        <FormView
          spec={spec}
          app="crm"
          schema={schema}
          record={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      ) : null}
    </div>
  );
}
