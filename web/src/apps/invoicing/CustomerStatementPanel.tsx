import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { formatMoney } from "../../lib/orgSettings";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { fullDate } from "../../ui/resource/fieldFormat";

interface Statement {
  customer: string;
  currency: string;
  start: string;
  end: string;
  opening_cents: number;
  closing_cents: number;
  rows: { at: string; kind: "invoice" | "payment"; number: string; amount_cents: number; balance_cents: number }[];
}

/** A customer's statement (roadmap item 5): the last 90 days of invoices
 * and payments with the balance carried in, as a customer asking "what do
 * I owe you?" expects it. Print sends just the statement. Hidden on an
 * older Invoicing without it. */
export function CustomerStatementPanel({ customerId }: { customerId: string }) {
  const [st, setSt] = useState<Statement | null>(null);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    api
      .get<Statement>(`/api/invoicing/customers/${customerId}/statement`)
      .then(setSt)
      .catch((err) => err instanceof ApiError && err.status === 404 && setGone(true));
  }, [customerId]);

  if (gone || !st) return null;
  const money = (c: number) => formatMoney(c, { currency: st.currency || undefined });

  function print() {
    const w = window.open("", "_blank", "width=720,height=900");
    if (!w || !st) return;
    const esc = (s: string) => s.replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[ch]!);
    const rows = st.rows
      .map((r) => `<tr><td>${fullDate(r.at, false)}</td><td>${r.kind === "invoice" ? "Invoice" : "Payment"} ${esc(r.number)}</td><td class=n>${money(r.amount_cents)}</td><td class=n>${money(r.balance_cents)}</td></tr>`)
      .join("");
    w.document.write(
      `<!doctype html><meta charset=utf-8><title>Statement: ${esc(st.customer)}</title><style>body{font:14px system-ui;margin:32px}table{width:100%;border-collapse:collapse}td,th{padding:6px;border-bottom:1px solid #ddd;text-align:left}.n{text-align:right;font-variant-numeric:tabular-nums}</style>` +
        `<h1>Statement</h1><p>${esc(st.customer)}<br>${fullDate(st.start, false)} to ${fullDate(st.end, false)}</p>` +
        `<table><tr><th>Date</th><th>What</th><th class=n>Amount</th><th class=n>Balance</th></tr><tr><td></td><td>Brought forward</td><td></td><td class=n>${money(st.opening_cents)}</td></tr>${rows}</table>` +
        `<p><strong>Owed now: ${money(st.closing_cents)}</strong></p>`,
    );
    w.document.close();
    w.focus();
    w.print();
  }

  return (
    <Card style={{ marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
        <div className="field-label">Statement, last 90 days</div>
        <Button type="button" size="sm" variant="secondary" onClick={print}>
          Print
        </Button>
      </div>
      <table className="table" style={{ width: "100%", marginTop: 8 }}>
        <tbody>
          <tr>
            <td colSpan={2}>Brought forward</td>
            <td />
            <td style={{ textAlign: "right" }}>{money(st.opening_cents)}</td>
          </tr>
          {st.rows.map((r, i) => (
            <tr key={i}>
              <td>{fullDate(r.at, false)}</td>
              <td>
                {r.kind === "invoice" ? "Invoice" : "Payment"} {r.number}
              </td>
              <td style={{ textAlign: "right" }}>{money(r.amount_cents)}</td>
              <td style={{ textAlign: "right" }}>{money(r.balance_cents)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ margin: "8px 0 0", fontWeight: 600 }}>
        {st.closing_cents > 0 ? `Owes ${money(st.closing_cents)}` : st.closing_cents < 0 ? `In credit ${money(-st.closing_cents)}` : "Owes nothing"}
      </p>
    </Card>
  );
}
