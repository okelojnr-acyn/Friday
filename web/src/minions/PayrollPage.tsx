import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { ApiError } from "../lib/api";
import { fetchMyPayroll, type MyPayrollLine } from "../lib/minions";
import { formatMoney } from "../lib/orgSettings";

const period = (l: MyPayrollLine) => {
  const f = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
    });
  return `${f(l.period_start)} to ${f(l.period_end)} ${new Date(l.period_end).getFullYear()}`;
};

/** Where a pay line is, in words a person understands. */
function payState(l: MyPayrollLine): { label: string; step: number } {
  if (l.line_status === "paid" || l.line_status === "confirmed")
    return { label: "Paid", step: 3 };
  if (l.line_status === "failed")
    return { label: "Payment didn't go through. Ask your manager", step: 2 };
  if (l.line_status === "sent") return { label: "On its way", step: 2 };
  if (l.run_status === "approved")
    return { label: "Approved, not sent yet", step: 1 };
  return { label: "Being prepared", step: 0 };
}

const STEPS = ["Prepared", "Approved", "Sent", "Paid"];

/** Pay: the latest pay as a slip (period, amount, where it is), then the
 * earlier ones. Read-only: approving and paying are on Friday's People >
 * Payroll. Payslips with deductions come in HR plan phase 2. */
export function PayrollPage() {
  const [lines, setLines] = useState<MyPayrollLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMyPayroll()
      .then((rows) =>
        setLines(
          [...rows].sort((a, b) => b.period_end.localeCompare(a.period_end)),
        ),
      )
      .catch((err) =>
        setError(
          err instanceof ApiError ? err.message : "Could not load your pay",
        ),
      );
  }, []);

  const [latest, ...earlier] = lines ?? [];
  const state = latest ? payState(latest) : null;

  return (
    <div className="page minions-page">
      <header className="minions-head">
        <h1 className="page-title">Pay</h1>
        <Link to="/wallet" className="btn btn-secondary btn-sm">
          Payout details
        </Link>
      </header>

      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      {!lines && !error ? (
        <div className="spinner">Loading your pay…</div>
      ) : null}

      {lines && !latest ? (
        <div className="minions-empty">
          <p className="minions-empty-title">No pay yet</p>
          <p className="field-label">
            Each time the business runs payroll, your pay shows up here.
          </p>
        </div>
      ) : null}

      {latest && state ? (
        <section className="minions-slip" aria-label="Latest pay">
          <p className="field-label">{period(latest)}</p>
          <p className="minions-slip-amount">
            {formatMoney(latest.net_cents || latest.gross_amount_cents, {
              currency: latest.currency,
            })}
          </p>
          <Payslip line={latest} />
          <p className="minions-slip-state">{state.label}</p>
          <ol className="minions-steps" aria-label="Progress">
            {STEPS.map((s, i) => (
              <li
                key={s}
                className={i <= state.step ? "reached" : undefined}
                aria-current={i === state.step ? "step" : undefined}
              >
                {s}
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      {earlier.length ? (
        <section aria-label="Earlier pay">
          <h2 className="minions-group">Earlier</h2>
          <ul className="minions-rows">
            {earlier.map((l) => (
              <li key={l.payroll_run_id} className="minions-row">
                <div className="minions-row-main">
                  <span className="minions-row-title">
                    {formatMoney(l.gross_amount_cents, {
                      currency: l.currency,
                    })}
                  </span>
                  <span className="field-label">{period(l)}</span>
                </div>
                <span className="field-label">{payState(l).label}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

/** Gross, what came off it, and what reaches you. */
function Payslip({ line: l }: { line: MyPayrollLine }) {
  const off = [
    ["NSSF", l.nssf_cents],
    ["SHIF", l.shif_cents],
    ["Housing Levy", l.levy_cents],
    ["PAYE (income tax)", l.paye_cents],
  ].filter(([, v]) => Number(v) > 0) as [string, number][];
  if (!off.length) return null;
  const m = (c: number) => formatMoney(c, { currency: l.currency });
  return (
    <dl className="minions-payslip">
      <dt>Gross pay</dt>
      <dd>{m(l.gross_amount_cents)}</dd>
      {off.map(([k, v]) => (
        <div key={k} className="minions-payslip-off">
          <dt>{k}</dt>
          <dd>−{m(v)}</dd>
        </div>
      ))}
      <dt className="minions-payslip-net">You get</dt>
      <dd className="minions-payslip-net">{m(l.net_cents || l.gross_amount_cents)}</dd>
    </dl>
  );
}
