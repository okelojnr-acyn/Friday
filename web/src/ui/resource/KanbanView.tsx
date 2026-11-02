import { useState } from "react";
import type { RecordRow, ResourceSpec } from "../../lib/types";
import { Avatar } from "../Avatar";
import { Icon } from "../Icon";
import { PriorityFlag } from "../PriorityFlag";
import { statusTone } from "../Badge";
import { formatCellValue, initials, isDueDateField, isPersonField, isPriorityField, sumCents } from "./fieldFormat";

interface KanbanViewProps {
  spec: ResourceSpec;
  records: RecordRow[];
  onCardClick: (record: RecordRow) => void;
  onMove: (record: RecordRow, newGroupValue: string) => void;
}

const TONE_VAR: Record<string, string> = {
  success: "var(--success)",
  danger: "var(--danger)",
  accent: "var(--accent)",
  neutral: "var(--border)",
};

export function KanbanView({ spec, records, onCardClick, onMove }: KanbanViewProps) {
  const groupField = spec.fields.find((f) => f.name === spec.kanbanGroupBy);
  const [dragOverColumn, setDragOverColumn] = useState<string | null>(null);

  if (!groupField) {
    return <div className="empty-state">This view isn't configured with a group-by field.</div>;
  }

  const columns =
    groupField.options ??
    Array.from(new Set(records.map((r) => String(r[groupField.name] ?? "")))).filter(Boolean);

  const titleField = spec.fields.find((f) => f.listVisible && f.name !== groupField.name);
  const personField = spec.fields.find(isPersonField);
  const dueField = spec.fields.find(isDueDateField);
  const priorityField = spec.fields.find(isPriorityField);
  const currencyField = spec.fields.find((f) => f.type === "currency");
  const subFields = spec.fields.filter(
    (f) =>
      f.listVisible &&
      f.name !== groupField.name &&
      f !== titleField &&
      f !== personField &&
      f !== dueField &&
      f !== priorityField &&
      f !== currencyField,
  );

  return (
    <div className="kanban-board">
      {columns.map((col, i) => {
        const cardsInColumn = records.filter((r) => String(r[groupField.name] ?? "") === col);
        const fillPct = Math.round(((i + 1) / columns.length) * 100);
        const tone = TONE_VAR[statusTone(col) ?? "neutral"];
        const sum = currencyField ? sumCents(cardsInColumn, currencyField) : null;

        return (
          <div className="kanban-column" key={col}>
            <div className="kanban-column-header">
              <div className="kanban-column-title-row">
                <span>
                  {col} <span className="kanban-column-count">{cardsInColumn.length}</span>
                </span>
                {sum !== null ? (
                  <span className="kanban-column-sum">${(sum / 100).toFixed(0)}</span>
                ) : null}
              </div>
              <div className="kanban-stage-bar">
                <span style={{ width: `${fillPct}%`, background: tone }} />
              </div>
            </div>
            <div
              className={`kanban-dropzone${dragOverColumn === col ? " drag-over" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setDragOverColumn(col);
              }}
              onDragLeave={() => setDragOverColumn((cur) => (cur === col ? null : cur))}
              onDrop={(e) => {
                e.preventDefault();
                setDragOverColumn(null);
                const id = e.dataTransfer.getData("text/plain");
                const record = records.find((r) => r.id === id);
                if (record && String(record[groupField.name] ?? "") !== col) {
                  onMove(record, col);
                }
              }}
            >
              {cardsInColumn.map((record) => {
                const personValue = personField ? String(record[personField.name] ?? "") : "";
                return (
                  <div
                    key={record.id}
                    className="kanban-card"
                    draggable
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", record.id)}
                    onClick={() => onCardClick(record)}
                  >
                    <div className="kanban-card-title">
                      {titleField ? formatCellValue(titleField, record[titleField.name]) : record.id}
                    </div>
                    {subFields.slice(0, 1).map((f) => (
                      <div key={f.name} className="kanban-card-sub">
                        {formatCellValue(f, record[f.name])}
                      </div>
                    ))}
                    {currencyField ? (
                      <div className="kanban-card-sub" style={{ color: "var(--text)", fontWeight: 600 }}>
                        {formatCellValue(currencyField, record[currencyField.name])}
                      </div>
                    ) : null}
                    <div className="kanban-card-foot">
                      <div className="kanban-card-meta">
                        {priorityField ? (
                          <PriorityFlag value={String(record[priorityField.name] ?? "medium")} />
                        ) : null}
                        {dueField && record[dueField.name] ? (
                          <span className="kanban-card-meta-item">
                            <Icon name="clock" size={12} />
                            {formatCellValue(dueField, record[dueField.name])}
                          </span>
                        ) : null}
                      </div>
                      {personField && personValue ? (
                        <Avatar label={initials(personValue)} title={personValue} size={22} />
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
