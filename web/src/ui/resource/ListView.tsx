import { Fragment, useEffect, useState } from "react";
import type { FieldSpec, RecordRow, ResourceSpec } from "../../lib/types";
import { Avatar } from "../Avatar";
import { Badge } from "../Badge";
import { PriorityFlag } from "../PriorityFlag";
import type { ReactNode } from "react";
import { formatCellValue, initials, isOverdue, isPersonField, isPriorityField, sumCents } from "./fieldFormat";
import { statusTone } from "../Badge";
import { resolveReferenceLabel } from "../../lib/referenceCache";
import { formatMoney } from "../../lib/orgSettings";

interface ListViewProps {
  spec: ResourceSpec;
  records: RecordRow[];
  onRowClick: (record: RecordRow) => void;
  /** A search or tab hides everything (say so) vs. truly nothing yet. */
  filtered?: boolean;
  /** The way to start, shown when there's nothing yet. */
  emptyAction?: ReactNode;
}

// Numbers, money, dates and statuses never break across lines.
const NOWRAP = new Set(["currency", "date", "datetime", "select", "number"]);
const cellClass = (f: FieldSpec) =>
  [
    f.type === "currency" ? "cell-currency" : "",
    NOWRAP.has(f.type) || f.name === "number" ? "cell-nowrap" : "",
    // Long text (a memo, a description) stays two lines, not a tall column.
    f.type === "text" || f.type === "textarea" ? "cell-clamp" : "",
  ]
    .filter(Boolean)
    .join(" ") || undefined;

/** The column to group rows by day: created_at, else the first date
 * column, and only when the rows are already in that column's order
 * (grouping an unordered list would mislead). */
export function dayField(columns: FieldSpec[], records: RecordRow[]): FieldSpec | null {
  if (records.length < 5) return null;
  const f =
    columns.find((c) => c.name === "created_at") ?? columns.find((c) => c.type === "datetime" || c.type === "date");
  if (!f) return null;
  const times = records.map((r) => Date.parse(String(r[f.name] ?? "")));
  if (times.some(Number.isNaN)) return null;
  const desc = times.every((t, i) => i === 0 || t <= times[i - 1]);
  const asc = times.every((t, i) => i === 0 || t >= times[i - 1]);
  return desc || asc ? f : null;
}

const dayKey = (v: unknown) => new Date(String(v)).toDateString();

/** "Today", "Yesterday", else "Mon, 24 Nov" (with the year when it isn't this one). */
function dayLabel(v: unknown): string {
  const d = new Date(String(v));
  const today = new Date();
  const yesterday = new Date(Date.now() - 86_400_000);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(d.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}),
  }).format(d);
}

function ReferenceCell({ field, value }: { field: FieldSpec; value: unknown }) {
  const [label, setLabel] = useState<string | null>(null);
  const [app, resource] = (field.reference ?? "").split(".");

  useEffect(() => {
    if (!value || !app || !resource) {
      setLabel(null);
      return;
    }
    let cancelled = false;
    resolveReferenceLabel(app, resource, String(value)).then((l) => !cancelled && setLabel(l));
    return () => {
      cancelled = true;
    };
  }, [app, resource, value]);

  if (!value) return <>—</>;
  return <>{label ?? "…"}</>;
}

function Cell({ field, value, record }: { field: FieldSpec; value: unknown; record: RecordRow }) {
  if (isOverdue(field, record)) {
    return (
      // Wraps under the date when the column is tight (Invoices scrolled sideways).
      <span style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
        {formatCellValue(field, value, record)}
        <Badge tone="danger">Overdue</Badge>
      </span>
    );
  }
  if (isPersonField(field) && value) {
    const v = String(value);
    return (
      <span className="cell-with-avatar">
        <Avatar label={initials(v)} title={v} size={22} />
        {v}
      </span>
    );
  }
  if (isPriorityField(field) && value) {
    return <PriorityFlag value={String(value)} />;
  }
  if (field.type === "reference") {
    return <ReferenceCell field={field} value={value} />;
  }
  if (field.type === "select" && (field.name === "status" || field.name === "stage") && value) {
    return <Badge tone={statusTone(String(value))}>{String(value).replace(/_/g, " ")}</Badge>;
  }
  if (field.type === "datetime" && typeof value === "string") {
    return <span title={new Date(value).toLocaleString()}>{formatCellValue(field, value, record)}</span>;
  }
  return <>{formatCellValue(field, value, record)}</>;
}

export function ListView({ spec, records, onRowClick, filtered, emptyAction }: ListViewProps) {
  const columns = spec.fields.filter((f) => f.listVisible);
  const currencyColumns = columns.filter((f) => f.type === "currency");
  const byDay = dayField(columns, records);

  if (records.length === 0) {
    return filtered ? (
      <div className="empty-state">Nothing matches. Clear the search or pick another tab.</div>
    ) : (
      <div className="empty-state" style={{ display: "grid", gap: 12, justifyItems: "center" }}>
        <span>No {spec.labelPlural.toLowerCase()} yet.</span>
        {emptyAction}
      </div>
    );
  }

  return (
    <div className="card" style={{ overflowX: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            {columns.map((f) => (
              <th key={f.name} className={f.type === "currency" ? "col-currency cell-nowrap" : undefined}>
                {f.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((record, i) => (
            <Fragment key={record.id}>
              {byDay && (i === 0 || dayKey(record[byDay.name]) !== dayKey(records[i - 1][byDay.name])) ? (
                <tr className="row-day">
                  <th scope="rowgroup" colSpan={columns.length}>
                    {dayLabel(record[byDay.name])}
                  </th>
                </tr>
              ) : null}
              <tr
                tabIndex={0}
                onClick={() => onRowClick(record)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onRowClick(record);
                  }
                }}
              >
                {columns.map((f) => (
                  <td key={f.name} className={cellClass(f)}>
                    {f.type === "text" || f.type === "textarea" ? (
                      <span className="clamp-2">
                        <Cell field={f} value={record[f.name]} record={record} />
                      </span>
                    ) : (
                      <Cell field={f} value={record[f.name]} record={record} />
                    )}
                  </td>
                ))}
              </tr>
            </Fragment>
          ))}
        </tbody>
        {currencyColumns.length > 0 ? (
          <tfoot>
            <tr style={{ cursor: "default" }}>
              {columns.map((f) => (
                <td key={f.name} className={f.type === "currency" ? "cell-currency" : undefined}>
                  {f.type === "currency" ? formatMoney(sumCents(records, f)) : ""}
                </td>
              ))}
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}
