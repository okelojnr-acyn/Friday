import { useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { fetchMyPayroll, type MyPayrollLine } from "../lib/minions";
import { Card } from "../ui/Card";
import { Badge, statusTone } from "../ui/Badge";

/** Read-only -- approve/pay/refresh-status stay admin actions on the
 * main Friday shell's payroll_run resource screens. This just shows an
 * employee their own payroll history (GET /me/payroll), never anyone
 * else's. */
export function PayrollPage() {
  const [lines, setLines] = useState<MyPayrollLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMyPayroll()
      .then(setLines)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load your payroll history"));
  }, []);

  if (error) return <div className="page error-banner">{error}</div>;
  if (!lines) return <div className="page spinner">Loading...</div>;

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Payroll</h1>
      </div>

      {lines.length === 0 ? (
        <div className="empty-state">No payroll runs yet.</div>
      ) : (
        lines.map((l) => (
          <Card key={l.payroll_run_id} style={{ marginBottom: 10 }}>
            <div className="pos-totals-row">
              <span>
                {new Date(l.period_start).toLocaleDateString()} &ndash; {new Date(l.period_end).toLocaleDateString()}
              </span>
              <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span>
                  {(l.gross_amount_cents / 100).toFixed(2)} {l.currency}
                </span>
                <Badge tone={statusTone(l.line_status)}>{l.line_status}</Badge>
              </span>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
