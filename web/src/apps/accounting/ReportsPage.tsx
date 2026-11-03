import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../../lib/api";
import {
  fetchAccountLedger,
  fetchAccounts,
  fetchBalanceSheet,
  fetchCashFlow,
  fetchProfitAndLoss,
  type Account,
  type BalanceSheet,
  type CashFlow,
  type LedgerLine,
  type ProfitAndLoss,
  type ReportLine,
} from "../../lib/accounting";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { FieldWrap, Input, Select } from "../../ui/Field";
import { Icon } from "../../ui/Icon";

function fmt(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${(Math.abs(cents) / 100).toFixed(2)}`;
}

function startOfYear(): string {
  return `${new Date().getFullYear()}-01-01`;
}

function today(): string {
  return new Date().toISOString().slice(0, 10);
}

type Tab = "pnl" | "balance-sheet" | "cash-flow" | "ledger";

/** Accounting's one hand-written screen (same justification as the POS
 * register and Web3's Treasury -- see ARCHITECTURE.md): these are
 * aggregation reads over the ledger, not CRUD, so they don't go through
 * the generic ResourceSpec renderer. The raw Account/Journal Entry lists
 * are still reachable at /accounting/account and /accounting/journal_entry
 * through the normal schema-driven screens. */
export function ReportsPage() {
  const [tab, setTab] = useState<Tab>("pnl");
  const [error, setError] = useState<string | null>(null);

  const [startDate, setStartDate] = useState(startOfYear());
  const [endDate, setEndDate] = useState(today());
  const [asOfDate, setAsOfDate] = useState(today());

  const [pnl, setPnl] = useState<ProfitAndLoss | null>(null);
  const [balanceSheet, setBalanceSheet] = useState<BalanceSheet | null>(null);
  const [cashFlow, setCashFlow] = useState<CashFlow | null>(null);

  const [accounts, setAccounts] = useState<Account[]>([]);
  const [ledgerAccountId, setLedgerAccountId] = useState("");
  const [ledger, setLedger] = useState<LedgerLine[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetchAccounts()
      .then((rows) => {
        setAccounts(rows);
        if (rows.length > 0) setLedgerAccountId((cur) => cur || rows[0].id);
      })
      .catch(() => setAccounts([]));
  }, []);

  async function runPnl() {
    setLoading(true);
    setError(null);
    try {
      setPnl(await fetchProfitAndLoss(startDate, endDate));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the P&L report");
    } finally {
      setLoading(false);
    }
  }

  async function runBalanceSheet() {
    setLoading(true);
    setError(null);
    try {
      setBalanceSheet(await fetchBalanceSheet(asOfDate));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the balance sheet");
    } finally {
      setLoading(false);
    }
  }

  async function runCashFlow() {
    setLoading(true);
    setError(null);
    try {
      setCashFlow(await fetchCashFlow(startDate, endDate));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the cash flow report");
    } finally {
      setLoading(false);
    }
  }

  async function runLedger() {
    if (!ledgerAccountId) return;
    setLoading(true);
    setError(null);
    try {
      setLedger(await fetchAccountLedger(ledgerAccountId));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the ledger");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (tab === "pnl") runPnl();
    else if (tab === "balance-sheet") runBalanceSheet();
    else if (tab === "cash-flow") runCashFlow();
    else if (tab === "ledger" && ledgerAccountId) runLedger();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  function renderReportLines(lines: ReportLine[]) {
    return lines.map((l) => (
      <div key={l.account_id} className="pos-totals-row">
        <span>
          {l.code} · {l.name}
        </span>
        <span>{fmt(l.amount_cents)}</span>
      </div>
    ));
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1 className="page-title">Reports</h1>
          <nav style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Link to="/accounting/account" className="btn btn-sm btn-pill btn-secondary">
              Chart of Accounts
            </Link>
            <Link to="/accounting/journal_entry" className="btn btn-sm btn-pill btn-secondary">
              Journal Entries
            </Link>
          </nav>
          <nav style={{ display: "flex", gap: 8, marginTop: 10 }}>
            <Button size="sm" variant={tab === "pnl" ? "primary" : "secondary"} onClick={() => setTab("pnl")}>
              Profit &amp; Loss
            </Button>
            <Button
              size="sm"
              variant={tab === "balance-sheet" ? "primary" : "secondary"}
              onClick={() => setTab("balance-sheet")}
            >
              Balance Sheet
            </Button>
            <Button
              size="sm"
              variant={tab === "cash-flow" ? "primary" : "secondary"}
              onClick={() => setTab("cash-flow")}
            >
              Cash Flow
            </Button>
            <Button size="sm" variant={tab === "ledger" ? "primary" : "secondary"} onClick={() => setTab("ledger")}>
              <Icon name="ledger" size={13} /> Ledger
            </Button>
          </nav>
        </div>
      </div>

      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      {(tab === "pnl" || tab === "cash-flow") && (
        <Card style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <FieldWrap label="Start date">
              <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
            </FieldWrap>
            <FieldWrap label="End date">
              <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
            </FieldWrap>
            <Button onClick={tab === "pnl" ? runPnl : runCashFlow} disabled={loading}>
              {loading ? "Loading..." : "Run"}
            </Button>
          </div>
        </Card>
      )}

      {tab === "balance-sheet" && (
        <Card style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <FieldWrap label="As of date">
              <Input type="date" value={asOfDate} onChange={(e) => setAsOfDate(e.target.value)} />
            </FieldWrap>
            <Button onClick={runBalanceSheet} disabled={loading}>
              {loading ? "Loading..." : "Run"}
            </Button>
          </div>
        </Card>
      )}

      {tab === "ledger" && (
        <Card style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
            <FieldWrap label="Account">
              <Select value={ledgerAccountId} onChange={(e) => setLedgerAccountId(e.target.value)}>
                {accounts.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.code} · {a.name}
                  </option>
                ))}
              </Select>
            </FieldWrap>
            <Button onClick={runLedger} disabled={loading}>
              {loading ? "Loading..." : "Run"}
            </Button>
          </div>
        </Card>
      )}

      {tab === "pnl" && pnl ? (
        <Card>
          <div className="field-label" style={{ marginBottom: 8 }}>
            Income
          </div>
          {pnl.income.length === 0 ? <div className="empty-state">No income posted in this period.</div> : renderReportLines(pnl.income)}
          <div className="pos-totals-row" style={{ fontWeight: 600, marginTop: 4 }}>
            <span>Total income</span>
            <span>{fmt(pnl.total_income_cents)}</span>
          </div>

          <div className="field-label" style={{ marginTop: 16, marginBottom: 8 }}>
            Expenses
          </div>
          {pnl.expenses.length === 0 ? <div className="empty-state">No expenses posted in this period.</div> : renderReportLines(pnl.expenses)}
          <div className="pos-totals-row" style={{ fontWeight: 600, marginTop: 4 }}>
            <span>Total expenses</span>
            <span>{fmt(pnl.total_expenses_cents)}</span>
          </div>

          <div className="pos-totals-row" style={{ fontWeight: 700, marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <span>Net income</span>
            <span>{fmt(pnl.net_income_cents)}</span>
          </div>
        </Card>
      ) : null}

      {tab === "balance-sheet" && balanceSheet ? (
        <Card>
          <div className="field-label" style={{ marginBottom: 8 }}>
            Assets
          </div>
          {balanceSheet.assets.length === 0 ? <div className="empty-state">No asset balances.</div> : renderReportLines(balanceSheet.assets)}
          <div className="pos-totals-row" style={{ fontWeight: 600, marginTop: 4 }}>
            <span>Total assets</span>
            <span>{fmt(balanceSheet.total_assets_cents)}</span>
          </div>

          <div className="field-label" style={{ marginTop: 16, marginBottom: 8 }}>
            Liabilities
          </div>
          {balanceSheet.liabilities.length === 0 ? <div className="empty-state">No liability balances.</div> : renderReportLines(balanceSheet.liabilities)}
          <div className="pos-totals-row" style={{ fontWeight: 600, marginTop: 4 }}>
            <span>Total liabilities</span>
            <span>{fmt(balanceSheet.total_liabilities_cents)}</span>
          </div>

          <div className="field-label" style={{ marginTop: 16, marginBottom: 8 }}>
            Equity
          </div>
          {balanceSheet.equity.length === 0 ? <div className="empty-state">No equity balances.</div> : renderReportLines(balanceSheet.equity)}
          <div className="pos-totals-row">
            <span>Net income to date</span>
            <span>{fmt(balanceSheet.net_income_to_date_cents)}</span>
          </div>
          <div className="pos-totals-row" style={{ fontWeight: 600, marginTop: 4 }}>
            <span>Total equity</span>
            <span>{fmt(balanceSheet.total_equity_cents)}</span>
          </div>

          <div className="pos-totals-row" style={{ fontWeight: 700, marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <span>Assets = Liabilities + Equity</span>
            <span>
              {fmt(balanceSheet.total_assets_cents)} = {fmt(balanceSheet.total_liabilities_cents + balanceSheet.total_equity_cents)}
            </span>
          </div>
        </Card>
      ) : null}

      {tab === "cash-flow" && cashFlow ? (
        <Card>
          <div className="pos-totals-row">
            <span>Beginning cash balance</span>
            <span>{fmt(cashFlow.beginning_balance_cents)}</span>
          </div>

          <div className="field-label" style={{ marginTop: 16, marginBottom: 8 }}>
            Net change by source
          </div>
          {cashFlow.by_source.length === 0 ? (
            <div className="empty-state">No cash movement in this period.</div>
          ) : (
            cashFlow.by_source.map((l) => (
              <div key={l.source} className="pos-totals-row">
                <span style={{ textTransform: "capitalize" }}>{l.source}</span>
                <span>{fmt(l.net_cents)}</span>
              </div>
            ))
          )}

          <div className="pos-totals-row" style={{ fontWeight: 600, marginTop: 4 }}>
            <span>Net change</span>
            <span>{fmt(cashFlow.net_change_cents)}</span>
          </div>
          <div className="pos-totals-row" style={{ fontWeight: 700, marginTop: 16, borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <span>Ending cash balance</span>
            <span>{fmt(cashFlow.ending_balance_cents)}</span>
          </div>
        </Card>
      ) : null}

      {tab === "ledger" && ledger ? (
        <Card>
          {ledger.length === 0 ? (
            <div className="empty-state">No posted entries against this account yet.</div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Entry</th>
                  <th>Description</th>
                  <th>Debit</th>
                  <th>Credit</th>
                  <th>Balance</th>
                </tr>
              </thead>
              <tbody>
                {ledger.map((l) => (
                  <tr key={`${l.journal_entry_id}-${l.description}-${l.balance_cents}`}>
                    <td>{l.entry_date}</td>
                    <td>{l.number}</td>
                    <td>{l.description}</td>
                    <td>{l.debit_cents ? fmt(l.debit_cents) : ""}</td>
                    <td>{l.credit_cents ? fmt(l.credit_cents) : ""}</td>
                    <td>{fmt(l.balance_cents)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      ) : null}
    </div>
  );
}
