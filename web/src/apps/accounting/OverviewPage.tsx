import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../lib/api";
import { fetchBalanceSheet, fetchProfitAndLoss, type BalanceSheet, type ProfitAndLoss, type ReportLine } from "../../lib/accounting";
import { formatMoney } from "../../lib/orgSettings";
import { AppHint } from "../../shell/AppFrame";
import { Card } from "../../ui/Card";

const iso = (d: Date) => d.toISOString().slice(0, 10);

/** Accounting's front page (plan 18/19.5): what an owner checks first in
 * Xero or QuickBooks: the money you have, who owes you, what you owe, and
 * how this month is going. From the same balance sheet and profit &
 * loss as Reports, so the numbers always agree. */
export function OverviewPage() {
  const [sheet, setSheet] = useState<BalanceSheet | null>(null);
  const [month, setMonth] = useState<ProfitAndLoss | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const today = new Date();
    const first = new Date(today.getFullYear(), today.getMonth(), 1);
    Promise.all([fetchBalanceSheet(iso(today)), fetchProfitAndLoss(iso(first), iso(today))])
      .then(([b, p]) => {
        setSheet(b);
        setMonth(p);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the books"));
  }, []);

  const m = (cents: number) => formatMoney(cents);
  const pick = (lines: ReportLine[], test: (code: string) => boolean) => lines.filter((l) => test(l.code));
  const sum = (lines: ReportLine[]) => lines.reduce((t, l) => t + l.amount_cents, 0);

  if (error) return <div className="page error-banner">{error}</div>;
  if (!sheet || !month) return <div className="page spinner">Loading...</div>;

  const money = pick(sheet.assets, (c) => c.startsWith("10"));
  const owedToYou = pick(sheet.assets, (c) => c === "1200");
  const youOwe = sheet.liabilities;

  const tile = (title: string, total: number, lines: ReportLine[], to: string, empty: string) => (
    <Card>
      <div className="field-label">{title}</div>
      <div className="gauge-value" style={{ fontSize: 26 }}>
        {m(total)}
      </div>
      {lines.length ? (
        <ul className="books-lines">
          {lines.map((l) => (
            <li key={l.account_id}>
              <span>{l.name}</span>
              <span className="num">{m(l.amount_cents)}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="field-label" style={{ margin: "6px 0 0" }}>
          {empty}
        </p>
      )}
      <Link to={to} className="field-label">
        See the detail
      </Link>
    </Card>
  );

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Overview</h1>
          <AppHint />
        </div>
      </div>
      <div className="books-grid">
        {tile("Money you have", sum(money), money, "/accounting/reports", "No money accounts yet.")}
        {tile("Owed to you", sum(owedToYou), owedToYou, "/invoicing", "Nobody owes you.")}
        {tile("You owe", sum(youOwe), youOwe, "/accounting/reports", "You owe nothing.")}
        <Card>
          <div className="field-label">This month so far</div>
          <div className="gauge-value" style={{ fontSize: 26, color: month.net_income_cents < 0 ? "var(--danger)" : undefined }}>
            {m(month.net_income_cents)}
          </div>
          <ul className="books-lines">
            <li>
              <span>Income</span>
              <span className="num">{m(month.total_income_cents)}</span>
            </li>
            <li>
              <span>Expenses</span>
              <span className="num">{m(month.total_expenses_cents)}</span>
            </li>
          </ul>
          <Link to="/accounting/reports" className="field-label">
            Profit &amp; loss
          </Link>
        </Card>
      </div>
    </div>
  );
}
