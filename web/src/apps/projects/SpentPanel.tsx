import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { formatMoney } from "../../lib/orgSettings";
import type { RecordRow } from "../../lib/types";

/** Spending plan part D: what was spent on this project (against its
 * budget) or task, from approved and paid claims in Minions. */
export function SpentPanel({ record, kind }: { record: RecordRow; kind: "project" | "task" }) {
  const [spent, setSpent] = useState<{ currency: string; spent_cents: number }[] | null>(null);
  useEffect(() => {
    api
      .get<{ for_id: string; currency: string; spent_cents: number }[]>(`/api/minions/spends/spent?for_kind=${kind}`)
      .then((rows) => setSpent(rows.filter((r) => r.for_id === String(record.id))))
      .catch(() => setSpent(null)); // no Minions, or not allowed to see it
  }, [kind, record.id]);

  const budget = Number(record.budget_cents ?? 0);
  if (spent === null || (!spent.length && !budget)) return null;
  const total = spent.reduce((t, r) => t + r.spent_cents, 0);
  const currency = spent[0]?.currency;
  const over = budget > 0 && total > budget;
  return (
    <div className="card card-padded" style={{ marginTop: 16 }}>
      <p className="field-label" style={{ margin: 0 }}>
        Spent {formatMoney(total, currency ? { currency } : undefined)}
        {budget ? ` of a ${formatMoney(budget)} budget` : ""}
        {spent.length > 1 ? " (in more than one currency)" : ""}
      </p>
      {budget ? (
        <div
          role="meter"
          aria-label="Budget used"
          aria-valuemin={0}
          aria-valuemax={budget}
          aria-valuenow={Math.min(total, budget)}
          style={{ height: 8, borderRadius: 4, background: "var(--border)", marginTop: 8, overflow: "hidden" }}
        >
          <div style={{ width: `${Math.min(100, (total * 100) / budget)}%`, height: "100%", background: over ? "var(--danger, #c0392b)" : "var(--accent)" }} />
        </div>
      ) : null}
      {over ? <p className="field-label minions-flag">Over budget by {formatMoney(total - budget)}</p> : null}
    </div>
  );
}
