import { useEffect, useState } from "react";
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
  [f.type === "currency" ? "cell-currency" : "", NOWRAP.has(f.type) || f.name === "number" ? "cell-nowrap" : ""].filter(Boolean).join(" ") ||
  undefined;

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
      <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
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
  return <>{formatCellValue(field, value, record)}</>;
}

export function ListView({ spec, records, onRowClick, filtered, emptyAction }: ListViewProps) {
  const columns = spec.fields.filter((f) => f.listVisible);
  const currencyColumns = columns.filter((f) => f.type === "currency");

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
          {records.map((record) => (
            <tr key={record.id} onClick={() => onRowClick(record)}>
              {columns.map((f) => (
                <td key={f.name} className={cellClass(f)}>
                  <Cell field={f} value={record[f.name]} record={record} />
                </td>
              ))}
            </tr>
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
