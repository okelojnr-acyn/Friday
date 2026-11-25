import type { ExpenseClaim } from "../../lib/minions";
import { formatMoney } from "../../lib/orgSettings";
import type { RecordRow } from "../../lib/types";
import { ClaimDecision, ClaimMarkPaid } from "./ClaimActions";

const BASE = "/api/minions/salary_advances";

/** People > Salary advances, one advance: who it waits on, the decision,
 * paying it out, and how much has come back from pay. */
export function AdvanceReviewPanel({ record, onChanged }: { record: RecordRow; onChanged: (r: RecordRow) => void }) {
  const done = (c: ExpenseClaim) => onChanged(c as unknown as RecordRow);
  const money = (c: unknown) => formatMoney(Number(c) || 0, { currency: String(record.currency || "") || undefined });
  return (
    <div className="card card-padded" style={{ marginTop: 16 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>
        {money(record.amount_cents)}, paid back over {String(record.months)} pay {Number(record.months) === 1 ? "run" : "runs"}
      </div>
      {record.description ? <p className="field-label">For: {String(record.description)}</p> : null}
      {record.status === "submitted" && record.waiting_on_name ? (
        <p className="field-label">Waiting for {String(record.waiting_on_name)}</p>
      ) : null}
      {record.decided_by_name ? (
        <p className="field-label">
          {record.status === "rejected" ? "Turned down" : "Approved"} by {String(record.decided_by_name)}
          {record.decision_note ? `: ${String(record.decision_note)}` : ""}
        </p>
      ) : null}
      {record.status === "paid" || record.status === "recovered" ? (
        <p className="field-label">
          {money(record.recovered_cents)} of {money(record.amount_cents)} back from pay
        </p>
      ) : null}
      {record.status === "submitted" ? <ClaimDecision claim={record} onDone={done} base={BASE} /> : null}
      {record.status === "approved" ? <ClaimMarkPaid claim={record} onDone={done} base={BASE} /> : null}
    </div>
  );
}
