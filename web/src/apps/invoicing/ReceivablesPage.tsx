import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../../lib/api";
import { Card } from "../../ui/Card";

interface Buckets {
  current_cents: number;
  days_1_30_cents: number;
  days_31_60_cents: number;
  days_61_90_cents: number;
  days_over_90_cents: number;
  total_cents: number;
}

interface AgingRow extends Buckets {
  customer_id: string | null;
  customer_name: string;
  currency: string;
  invoice_count: number;
}

interface AgingReport {
  as_of: string;
  rows: AgingRow[];
  totals: (Buckets & { currency: string })[];
}

const COLUMNS: [keyof Buckets, string][] = [
  ["current_cents", "Not yet due"],
  ["days_1_30_cents", "1–30 days"],
  ["days_31_60_cents", "31–60 days"],
  ["days_61_90_cents", "61–90 days"],
  ["days_over_90_cents", "90+ days"],
  ["total_cents", "Total owed"],
];

function amount(cents: number): string {
  if (!cents) return "–";
  return (cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Invoicing's landing page: who owes the business money, and how late.
 * An aggregation read (GET /reports/ar-aging), not CRUD -- same
 * justification as CRM's PipelinePage and Accounting's ReportsPage. The
 * raw Invoice/Quote/Customer lists stay reachable through the
 * schema-driven screens linked in the header. */
export function ReceivablesPage() {
  const [report, setReport] = useState<AgingReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AgingReport>("/api/invoicing/reports/ar-aging")
      .then(setReport)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load receivables"));
  }, []);

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Receivables</h1>
          <nav style={{ display: "flex", gap: 8, marginTop: 10, flexWrap: "wrap" }}>
            <Link to="/invoicing/quote" className="btn btn-sm btn-pill btn-secondary">
              Quotes
            </Link>
            <Link to="/invoicing/invoice" className="btn btn-sm btn-pill btn-secondary">
              Invoices
            </Link>
            <Link to="/invoicing/customer" className="btn btn-sm btn-pill btn-secondary">
              Customers
            </Link>
            <Link to="/invoicing/pos_shift" className="btn btn-sm btn-pill btn-secondary">
              POS shifts
            </Link>
          </nav>
        </div>
      </div>

      {error ? <div className="error-banner">{error}</div> : null}
      {!report && !error ? <div className="spinner">Loading...</div> : null}

      {report && report.rows.length === 0 ? (
        <Card>
          <div className="field-label">
            Nothing outstanding. Invoices appear here once they're marked "sent" and until they're paid in full.
          </div>
        </Card>
      ) : null}

      {report && report.rows.length > 0 ? (
        <>
          <div className="dashboard-grid" style={{ marginBottom: 24 }}>
            {report.totals.map((t) => (
              <Card key={t.currency}>
                <div className="field-label">Owed to you ({t.currency})</div>
                <div className="gauge-value" style={{ fontSize: 28 }}>
                  {amount(t.total_cents)}
                </div>
                <div className="field-label">
                  {amount(t.total_cents - t.current_cents)} overdue
                  {t.days_over_90_cents ? ` · ${amount(t.days_over_90_cents)} over 90 days` : ""}
                </div>
              </Card>
            ))}
          </div>

          <Card style={{ overflowX: "auto" }}>
            <table className="data-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Customer</th>
                  <th style={{ textAlign: "left" }}>Currency</th>
                  {COLUMNS.map(([, label]) => (
                    <th key={label} style={{ textAlign: "right" }}>
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {report.rows.map((r) => (
                  <tr key={`${r.customer_id ?? "none"}-${r.currency}`}>
                    <td>
                      {r.customer_id ? (
                        <Link to={`/invoicing/invoice?customer_id=${r.customer_id}`}>{r.customer_name}</Link>
                      ) : (
                        r.customer_name
                      )}{" "}
                      <span className="field-label">({r.invoice_count})</span>
                    </td>
                    <td>{r.currency}</td>
                    {COLUMNS.map(([key]) => (
                      <td key={key} style={{ textAlign: "right", fontWeight: key === "total_cents" ? 600 : undefined }}>
                        {amount(r[key])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <div className="field-label" style={{ marginTop: 8 }}>
            As of {new Date(report.as_of).toLocaleString()} · ages count from each invoice's due date.
          </div>
        </>
      ) : null}
    </div>
  );
}
