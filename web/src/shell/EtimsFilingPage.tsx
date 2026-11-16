import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import {
  downloadVatSales,
  etimsDetail,
  listEtims,
  recordFiled,
  setBuyer,
  undoFiled,
  type EtimsLine,
  type EtimsRow,
} from "../lib/etims";
import { formatMoney } from "../lib/orgSettings";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";

const STATUS_LABEL: Record<EtimsRow["status"], string> = {
  unfiled: "To file",
  submitted: "Filed",
  failed: "KRA refused",
};

function thisMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

/** eTIMS filing (owner, 2026-11-16): the sales KRA needs an eTIMS invoice
 * for, laid out the way the eTIMS portal asks for them, and the invoice
 * number eTIMS gives back recorded against each. Filing is by hand until
 * automatic sending passes the production checks. */
export function EtimsFilingPage() {
  const { session } = useAuth();
  const canFile = session?.role === "owner" || session?.role === "admin";
  const [month, setMonth] = useState(thisMonth());
  const [scope, setScope] = useState<"pin" | "all">("pin");
  const [status, setStatus] = useState("unfiled");
  const [rows, setRows] = useState<EtimsRow[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!canFile) return;
    setRows(null);
    setError(null);
    listEtims(scope, status, month)
      .then(setRows)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the sales."));
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [scope, status, month, canFile]);

  function replaced(r: EtimsRow) {
    setRows((rs) => (rs ? rs.map((x) => (x.id === r.id ? r : x)) : rs));
  }

  if (!canFile) {
    return (
      <div className="page" style={{ maxWidth: 960 }}>
        <h1 className="page-title">eTIMS filing</h1>
        <p className="field-label">Only owners and admins file sales with KRA.</p>
      </div>
    );
  }

  return (
    <div className="page" style={{ maxWidth: 960 }}>
      <div className="page-header">
        <h1 className="page-title">eTIMS filing</h1>
      </div>
      <ol className="card card-padded" style={{ margin: "0 0 16px", paddingLeft: 36, display: "grid", gap: 6, maxWidth: "70ch" }}>
        <li>Open a sale below. It shows the buyer's PIN, each item with its tax type, and the VAT.</li>
        <li>
          Enter it in KRA's eTIMS (the{" "}
          <a href="https://etims.kra.go.ke" target="_blank" rel="noopener noreferrer">
            eTIMS portal
          </a>{" "}
          or the eTIMS app) exactly as shown.
        </li>
        <li>Type the invoice number eTIMS gives back and save. The sale moves to Filed.</li>
      </ol>
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end", marginBottom: 16 }}>
        <FieldWrap label="Month">
          <Input type="month" value={month} onChange={(e) => setMonth(e.target.value || thisMonth())} style={{ width: 170 }} />
        </FieldWrap>
        <FieldWrap label="Sales">
          <Select value={scope} onChange={(e) => setScope(e.target.value as "pin" | "all")}>
            <option value="pin">To businesses (buyer PIN)</option>
            <option value="all">All sales</option>
          </Select>
        </FieldWrap>
        <FieldWrap label="Status">
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="unfiled">To file</option>
            <option value="submitted">Filed</option>
            <option value="failed">KRA refused</option>
            <option value="any">All</option>
          </Select>
        </FieldWrap>
        <Button
          onClick={() => downloadVatSales(month).catch((err) => setError(err instanceof Error ? err.message : "Download failed."))}
        >
          Download VAT sales (CSV)
        </Button>
        <Link to="/settings/business?tab=etims" className="btn btn-secondary">
          eTIMS settings
        </Link>
      </div>
      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}
      {rows === null ? (
        <div className="card card-padded field-label">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="card card-padded field-label">
          {status === "unfiled" ? "Nothing to file for this month." : "No sales here for this month."}
        </div>
      ) : (
        <div className="card" style={{ overflow: "hidden" }}>
          {rows.map((r) => (
            <div key={r.id} style={{ borderBottom: "1px solid var(--border)" }}>
              <button
                type="button"
                onClick={() => setOpen(open === r.id ? null : r.id)}
                style={{
                  all: "unset",
                  cursor: "pointer",
                  display: "flex",
                  flexWrap: "wrap",
                  gap: "4px 16px",
                  alignItems: "center",
                  padding: "12px 16px",
                  width: "100%",
                  boxSizing: "border-box",
                }}
              >
                <span style={{ flex: "1 1 220px", minWidth: 0 }}>
                  <strong>{r.number}</strong>
                  {r.credit_note ? <span className="field-label"> · credit note for {r.original_number}</span> : null}
                  <br />
                  <span className="field-label">
                    {r.issued_at ? new Date(r.issued_at).toLocaleString() : ""}
                    {r.buyer_pin ? ` · ${r.buyer_pin}${r.buyer_name ? ` ${r.buyer_name}` : ""}` : " · walk-in"}
                  </span>
                </span>
                <span style={{ fontVariantNumeric: "tabular-nums", textAlign: "right" }}>
                  {formatMoney(r.total_cents)}
                  <br />
                  <span className="field-label">VAT {formatMoney(r.vat_cents)}</span>
                </span>
                <Badge tone={r.status === "submitted" ? "success" : r.status === "failed" ? "danger" : "neutral"}>
                  {STATUS_LABEL[r.status]}
                </Badge>
              </button>
              {open === r.id ? <FilingSheet row={r} onChanged={replaced} /> : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function FilingSheet({ row, onChanged }: { row: EtimsRow; onChanged: (r: EtimsRow) => void }) {
  const [lines, setLines] = useState<EtimsLine[] | null>(null);
  const [no, setNo] = useState("");
  const [pin, setPin] = useState(row.buyer_pin);
  const [name, setName] = useState(row.buyer_name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    etimsDetail(row.id)
      .then((d) => setLines(d.lines))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the sale."));
  }, [row.id]);

  async function run(fn: () => Promise<EtimsRow>) {
    setBusy(true);
    setError(null);
    try {
      onChanged(await fn());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  const filed = row.status === "submitted";
  return (
    <div style={{ padding: "0 16px 16px", display: "grid", gap: 12 }}>
      {error ? <div className="error-banner">{error}</div> : null}
      {row.credit_note ? (
        <p className="field-label" style={{ margin: 0 }}>
          A refund. In eTIMS, raise a credit note on invoice{" "}
          <strong>{row.original_etims_no || `${row.original_number} (file that sale first)`}</strong>.
        </p>
      ) : null}
      {!row.pin_ok ? <div className="error-banner">The buyer PIN doesn't look like a KRA PIN. Correct it before filing.</div> : null}
      {lines === null ? (
        <div className="field-label">Loading…</div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table className="table" style={{ minWidth: 560 }}>
            <thead>
              <tr>
                <th>Item</th>
                <th>Qty</th>
                <th className="col-currency">Unit price</th>
                <th className="col-currency">Discount</th>
                <th>Tax type</th>
                <th className="col-currency">Amount</th>
                <th className="col-currency">VAT</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={i}>
                  <td>{l.name}</td>
                  <td>
                    {l.quantity} {l.quantity_unit}
                  </td>
                  <td className="cell-currency">{formatMoney(l.unit_price_cents)}</td>
                  <td className="cell-currency">{l.discount_cents ? formatMoney(l.discount_cents) : ""}</td>
                  <td>{l.tax_code}</td>
                  <td className="cell-currency">{formatMoney(l.gross_cents)}</td>
                  <td className="cell-currency">{formatMoney(l.vat_cents)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              {Object.entries(row.by_code).map(([code, a]) => (
                <tr key={code}>
                  <td colSpan={5}>Tax type {code}</td>
                  <td className="cell-currency">{formatMoney(a.gross_cents)}</td>
                  <td className="cell-currency">{formatMoney(a.vat_cents)}</td>
                </tr>
              ))}
            </tfoot>
          </table>
          <p className="field-label" style={{ margin: "6px 0 0" }}>Amounts include VAT.</p>
        </div>
      )}

      {!filed ? (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          <FieldWrap label="Buyer KRA PIN">
            <Input name="etims-buyer-pin" autoComplete="off" value={pin} maxLength={14} onChange={(e) => setPin(e.target.value.toUpperCase())} placeholder="Walk-in: leave empty" style={{ width: 180 }} />
          </FieldWrap>
          <FieldWrap label="Buyer name">
            <Input name="etims-buyer-name" autoComplete="off" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} />
          </FieldWrap>
          <Button disabled={busy || (pin === row.buyer_pin && name === row.buyer_name)} onClick={() => run(() => setBuyer(row.id, pin, name))}>
            Save buyer
          </Button>
        </div>
      ) : null}

      {filed ? (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <span>
            eTIMS invoice <strong style={{ fontFamily: "var(--font-mono, monospace)" }}>{row.etims_invoice_no}</strong>
            <span className="field-label">
              {" "}
              · {row.filed_by}
              {row.filed_at ? `, ${new Date(row.filed_at).toLocaleString()}` : ""}
            </span>
          </span>
          {row.receipt_check_url ? (
            <a href={row.receipt_check_url} target="_blank" rel="noopener noreferrer">
              Check on KRA
            </a>
          ) : null}
          {row.via === "manual" ? (
            <Button size="sm" disabled={busy} onClick={() => run(() => undoFiled(row.id))}>
              Undo
            </Button>
          ) : null}
        </div>
      ) : (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-end" }}>
          {row.error ? <div className="error-banner" style={{ flexBasis: "100%" }}>KRA said: {row.error}</div> : null}
          <FieldWrap label="Invoice number from eTIMS">
            <Input
              name="etims-invoice-no"
              autoComplete="off"
              value={no}
              maxLength={60}
              onChange={(e) => setNo(e.target.value)}
              style={{ width: 240, fontFamily: "var(--font-mono, monospace)" }}
            />
          </FieldWrap>
          <Button variant="primary" disabled={busy || !no.trim() || !row.pin_ok} onClick={() => run(() => recordFiled(row.id, no.trim()))}>
            Save as filed
          </Button>
        </div>
      )}
    </div>
  );
}
