import { useEffect, useState } from "react";
import type { FieldSpec, RecordRow, ResourceSpec } from "../../lib/types";
import { Avatar } from "../Avatar";
import { PriorityFlag } from "../PriorityFlag";
import { formatCellValue, initials, isPersonField, isPriorityField, sumCents } from "./fieldFormat";
import { resolveReferenceLabel } from "../../lib/referenceCache";

interface ListViewProps {
  spec: ResourceSpec;
  records: RecordRow[];
  onRowClick: (record: RecordRow) => void;
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

function Cell({ field, value }: { field: FieldSpec; value: unknown }) {
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
  return <>{formatCellValue(field, value)}</>;
}

export function ListView({ spec, records, onRowClick }: ListViewProps) {
  const columns = spec.fields.filter((f) => f.listVisible);
  const currencyColumns = columns.filter((f) => f.type === "currency");

  if (records.length === 0) {
    return <div className="empty-state">No {spec.labelPlural.toLowerCase()} yet.</div>;
  }

  return (
    <div className="card" style={{ overflowX: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            {columns.map((f) => (
              <th key={f.name} className={f.type === "currency" ? "col-currency" : undefined}>
                {f.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {records.map((record) => (
            <tr key={record.id} onClick={() => onRowClick(record)}>
              {columns.map((f) => (
                <td key={f.name} className={f.type === "currency" ? "cell-currency" : undefined}>
                  <Cell field={f} value={record[f.name]} />
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
                  {f.type === "currency" ? `$${(sumCents(records, f) / 100).toFixed(2)}` : ""}
                </td>
              ))}
            </tr>
          </tfoot>
        ) : null}
      </table>
    </div>
  );
}
