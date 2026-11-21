import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../lib/api";
import { downloadTextFile, parseCsv } from "../../lib/csv";
import { formatMoney } from "../../lib/orgSettings";
import { KERNEL_URL } from "../../lib/runtimeConfig";
import { loadSession } from "../../lib/session";
import { Button } from "../../ui/Button";
import { FieldWrap, Input } from "../../ui/Field";

function lastMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

async function fetchCsv(path: string): Promise<string> {
  const session = loadSession();
  const res = await fetch(`${KERNEL_URL}${path}`, {
    headers: session ? { Authorization: `Bearer ${session.token}` } : {},
  });
  if (!res.ok) throw new Error(`Could not load ${path.split("?")[0]} (${res.status})`);
  return res.text();
}

/** Sums a money column (shillings) of a schedule, skipping the header. */
function sum(rows: string[][], col: number): number {
  return rows.slice(1).reduce((s, r) => s + Math.round((Number.parseFloat(r[col] || "0") || 0) * 100), 0);
}

/** The month's VAT return (owner, 2026-11-16): the two files KRA's iTax
 * VAT3 return takes, sales (Section B) and purchases (Section F), and what
 * they add up to. The same figures Accounting books: VAT on sales owed,
 * VAT on purchases claimed back. */
export function VatReturnCard() {
  const [month, setMonth] = useState(lastMonth());
  const [sales, setSales] = useState<string | null>(null);
  const [purchases, setPurchases] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [books, setBooks] = useState<{ output_vat_cents: number; input_vat_cents: number } | null>(null);

  useEffect(() => {
    setSales(null);
    setPurchases(null);
    setBooks(null);
    setError(null);
    // Accounting's own figures for the month: the check that both sides agree.
    api.get<{ output_vat_cents: number; input_vat_cents: number }>(`/api/accounting/reports/vat?month=${month}`).then(setBooks, () => setBooks(null));
    fetchCsv(`/api/invoicing/etims/vat-sales.csv?month=${month}`).then(setSales, (e) => setError(e.message));
    fetchCsv(`/api/inventory/purchase_orders/vat-purchases.csv?month=${month}`).then(setPurchases, (e) => setError(e.message));
  }, [month]);

  const s = sales ? parseCsv(sales) : null;
  const p = purchases ? parseCsv(purchases) : null;
  // Sales: Taxable Value col 7, VAT col 8. Purchases: 8 and 9.
  const outVat = s ? sum(s, 8) : 0;
  const inVat = p ? sum(p, 9) : 0;
  const missing = p ? p.slice(1).filter((r) => r[12]).length : 0;
  const outOff = books && s ? books.output_vat_cents - outVat : 0;
  const inOff = books && p ? books.input_vat_cents - inVat : 0;
  const booksCell = (cents: number | undefined) => (books && cents !== undefined ? formatMoney(cents) : "…");

  return (
    <div className="card card-padded form-grid" style={{ marginTop: 16 }}>
      <h2 style={{ fontSize: 18, margin: 0 }}>VAT return</h2>
      <p className="field-label" style={{ maxWidth: "62ch", margin: 0 }}>
        The two schedules KRA's iTax VAT3 return asks for, in its columns. Paste them into the VAT3 template and upload it
        on iTax. iTax pre-fills sales from eTIMS, so the sales file is your check against it.
      </p>
      <FieldWrap label="Month">
        <Input type="month" value={month} onChange={(e) => setMonth(e.target.value || lastMonth())} style={{ width: 170 }} />
      </FieldWrap>
      {error ? <div className="error-banner">{error}</div> : null}
      <table className="table" style={{ maxWidth: 620 }}>
        <thead>
          <tr>
            <th />
            <th className="cell-currency">VAT return files</th>
            <th className="cell-currency">Books (Accounting)</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Sales before VAT</td>
            <td className="cell-currency">{s ? formatMoney(sum(s, 7)) : "…"}</td>
            <td />
          </tr>
          <tr>
            <td>VAT on sales (output)</td>
            <td className="cell-currency">{s ? formatMoney(outVat) : "…"}</td>
            <td className="cell-currency">{booksCell(books?.output_vat_cents)}</td>
          </tr>
          <tr>
            <td>Purchases before VAT</td>
            <td className="cell-currency">{p ? formatMoney(sum(p, 8)) : "…"}</td>
            <td />
          </tr>
          <tr>
            <td>VAT on purchases (input)</td>
            <td className="cell-currency">{p ? formatMoney(inVat) : "…"}</td>
            <td className="cell-currency">{booksCell(books?.input_vat_cents)}</td>
          </tr>
          <tr>
            <td>
              <strong>{outVat - inVat >= 0 ? "VAT to pay KRA" : "VAT to carry forward"}</strong>
            </td>
            <td className="cell-currency">
              <strong>{s && p ? formatMoney(Math.abs(outVat - inVat)) : "…"}</strong>
            </td>
            <td className="cell-currency">
              {books ? formatMoney(Math.abs(books.output_vat_cents - books.input_vat_cents)) : "…"}
            </td>
          </tr>
        </tbody>
      </table>
      {outOff || inOff ? (
        <div className="error-banner">
          The books and the VAT files differ by {formatMoney(Math.abs(outOff))} on sales VAT and{" "}
          {formatMoney(Math.abs(inOff))} on purchases VAT. Usual causes: an invoice issued this month but paid in
          another (the books count VAT when paid), a manual journal entry on a VAT account, or a sale near midnight
          at the month's edge. Check before filing.
        </div>
      ) : books && s && p ? (
        <div className="field-label">The books agree with both files.</div>
      ) : null}
      {missing ? (
        <div className="error-banner">
          {missing} purchase line{missing === 1 ? "" : "s"} lack the supplier's PIN or invoice number. KRA allows input VAT
          only with both: add them on the supplier and the purchase order.
        </div>
      ) : null}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <Button disabled={!sales} onClick={() => sales && downloadTextFile(`vat3-sales-${month}.csv`, sales)}>
          Download sales (Section B)
        </Button>
        <Button disabled={!purchases} onClick={() => purchases && downloadTextFile(`vat3-purchases-${month}.csv`, purchases)}>
          Download purchases (Section F)
        </Button>
        <Link to="/etims" className="btn btn-secondary">
          eTIMS filing
        </Link>
      </div>
    </div>
  );
}
