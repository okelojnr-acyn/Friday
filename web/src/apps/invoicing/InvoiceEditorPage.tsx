import { PickList } from "../../ui/PickList";
import { localDay } from "../../lib/localTime";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError } from "../../lib/api";
import { currentOrgSettings, formatMoney, useOrgSettings } from "../../lib/orgSettings";
import { createRecord, listRecords, updateRecord } from "../../lib/resourceApi";
import { getReferenceOptions } from "../../lib/referenceCache";
import type { FieldSpec, RecordRow } from "../../lib/types";
import { Button } from "../../ui/Button";
import { FieldWrap, Input, Select } from "../../ui/Field";
import { Icon } from "../../ui/Icon";
import { ReferenceInput } from "../../ui/resource/ReferenceInput";
import { amountInputToCents } from "../../ui/resource/fieldFormat";

interface Line {
  description: string;
  quantity: string;
  unitPrice: string;
  /** Percent as typed ("16"); sent as basis points. */
  taxPercent: string;
  productId?: string;
}

const CUSTOMER_FIELD: FieldSpec = {
  name: "customer_id",
  label: "Customer",
  type: "reference",
  required: false,
  options: null,
  reference: "invoicing.customer",
  listVisible: true,
  formVisible: true,
};

// "" = the customer's own payment terms (what the server does by itself).
const TERMS: [string, string][] = [
  ["", "Customer's terms"],
  ["0", "On receipt"],
  ["7", "In 7 days"],
  ["14", "In 14 days"],
  ["30", "In 30 days"],
  ["60", "In 60 days"],
];
const CURRENCIES = ["KES", "UGX", "TZS", "RWF", "USD", "EUR", "GBP", "IDR"];

/** Mirrors InvoiceLine on the server: net = qty x price, tax = floor(net x bp / 10000). */
function lineCents(l: Line): { net: number; tax: number } {
  const net = Math.trunc((Number(l.quantity) || 0) * amountInputToCents(l.unitPrice || "0"));
  const bp = Math.round((Number(l.taxPercent) || 0) * 100);
  return { net, tax: Math.floor((net * bp) / 10000) };
}

const addDays = (days: number) => {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return d;
};
const isoDay = (d: Date) => localDay(d); // the viewer's calendar, not UTC's

/** New invoice (owner, 2026-11-22: "issuing an invoice is quite a show";
 * build it the way the best invoicing tools do). The Stripe/Xero
 * pattern: one page, the form beside a live preview of what the customer
 * gets; lines picked from products; terms that set the due date; then
 * Save draft or Send, and a clear "done" with the pay link. */
export function InvoiceEditorPage() {
  const navigate = useNavigate();
  const org = useOrgSettings();
  const defaultTax = org.tax_rate_bp ? String(org.tax_rate_bp / 100) : "";
  const [customerId, setCustomerId] = useState<unknown>(null);
  const [customers, setCustomers] = useState<RecordRow[]>([]);
  const [currency, setCurrency] = useState(() => currentOrgSettings().currency || "KES");
  const [terms, setTerms] = useState("");
  const [repeats, setRepeats] = useState("");
  const [lines, setLines] = useState<Line[]>([{ description: "", quantity: "1", unitPrice: "", taxPercent: defaultTax }]);
  const [products, setProducts] = useState<RecordRow[]>([]);
  const [busy, setBusy] = useState<"draft" | "send" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<{ invoice: RecordRow; sent: boolean; email: string } | null>(null);
  const [payLink, setPayLink] = useState<string | null>(null);
  const [linkError, setLinkError] = useState<string | null>(null);

  useEffect(() => {
    listRecords("inventory", "product").then(setProducts).catch(() => setProducts([]));
  }, []);
  useEffect(() => {
    getReferenceOptions("invoicing", "customer").then(setCustomers);
  }, [customerId]);

  const customer = customers.find((c) => c.id === customerId) ?? null;
  const termsDays = terms === "" ? Number(customer?.payment_terms_days ?? 0) : Number(terms);
  const due = addDays(termsDays);
  const totals = useMemo(
    () =>
      lines.reduce(
        (acc, l) => {
          const { net, tax } = lineCents(l);
          return { net: acc.net + net, tax: acc.tax + tax };
        },
        { net: 0, tax: 0 },
      ),
    [lines],
  );
  const money = (cents: number) => formatMoney(cents, { currency });

  function setLine(i: number, patch: Partial<Line>) {
    setLines((cur) => cur.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }

  // Picking a product fills its price and tax. Shelf prices that already
  // include VAT are turned into the price before tax, so the invoice
  // total matches the shelf.
  function pickProduct(i: number, name: string) {
    const p = products.find((x) => String(x.name) === name);
    if (!p) return setLine(i, { description: name, productId: undefined });
    const bp = org.tax_rate_bp || 0;
    const price = Number(p.price_cents) || 0;
    const ex = org.prices_include_tax && bp ? Math.round((price * 10000) / (10000 + bp)) : price;
    setLine(i, { description: name, unitPrice: (ex / 100).toFixed(2), taxPercent: defaultTax, productId: String(p.id) });
  }

  async function save(send: boolean) {
    const valid = lines.filter((l) => l.description.trim());
    if (!valid.length) return setError("Add at least one item.");
    if (valid.some((l) => Number(l.taxPercent) < 0 || Number(l.taxPercent) > 100)) return setError("Tax must be between 0% and 100%.");
    if (send && !customerId) return setError("Pick who the invoice is for before sending it.");
    setBusy(send ? "send" : "draft");
    setError(null);
    try {
      const invoice = await createRecord("invoicing", "invoice", {
        customer_id: customerId || null,
        currency,
        recurring_interval: repeats,
        // Older invoicing apps ignore this and use the customer's terms.
        ...(terms !== "" ? { due_at: isoDay(due) } : {}),
        lines: valid.map((l) => ({
          description: l.description.trim(),
          quantity: Number(l.quantity) || 1,
          unit_price_cents: amountInputToCents(l.unitPrice || "0"),
          tax_rate_bp: Math.round((Number(l.taxPercent) || 0) * 100),
          ...(l.productId ? { product_id: l.productId } : {}),
        })),
      });
      const final = send ? await updateRecord("invoicing", "invoice", invoice.id, { status: "sent" }) : invoice;
      setDone({ invoice: final, sent: send, email: String(customer?.email ?? "") });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save the invoice.");
    } finally {
      setBusy(null);
    }
  }

  async function getPayLink(id: string) {
    setLinkError(null);
    try {
      const r = await api.post<{ redirect_url: string }>(`/api/invoicing/invoices/${id}/paystack-link`, {});
      setPayLink(r.redirect_url);
      await navigator.clipboard?.writeText(r.redirect_url).catch(() => {});
    } catch (err) {
      setLinkError(err instanceof ApiError ? err.message : "Could not make a pay link.");
    }
  }

  if (done) {
    const { invoice, sent, email } = done;
    return (
      <div className="page">
        <div className="card card-padded invoice-done">
          <span className="invoice-done-icon">
            <Icon name="send" size={22} />
          </span>
          <h1 className="page-title">
            {sent ? `Invoice ${invoice.number} sent` : `Draft ${invoice.number} saved`}
          </h1>
          <p style={{ margin: 0 }}>
            {sent
              ? email
                ? `We emailed it to ${email}. They can pay from the email.`
                : "This customer has no email on file, so nothing was emailed. Share the pay link instead."
              : "It isn't sent yet. Open it from Invoices when you're ready."}
          </p>
          {sent ? (
            <div style={{ display: "grid", gap: 8 }}>
              <Button variant={email ? "secondary" : "primary"} onClick={() => getPayLink(invoice.id)}>
                {payLink ? "Copied: get it again" : "Copy the pay link"}
              </Button>
              {payLink ? <code className="invoice-link">{payLink}</code> : null}
              {linkError ? <div className="error-banner">{linkError}</div> : null}
            </div>
          ) : null}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <Link to="/invoicing/invoice" className="btn btn-secondary btn-pill">
              Back to invoices
            </Link>
            <Button
              className="btn-pill"
              onClick={() => {
                setDone(null);
                setPayLink(null);
                setCustomerId(null);
                setLines([{ description: "", quantity: "1", unitPrice: "", taxPercent: defaultTax }]);
              }}
            >
              New invoice
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const productOptions = products.map((p) => ({ value: String(p.name), label: String(p.name), hint: [p.sku, money(Number(p.price_cents) || 0)].filter(Boolean).join(", ") }));

  return (
    <div className="page invoice-editor">
      <div className="page-header">
        <div>
          <Link to="/invoicing/invoice" className="field-label">
            ← Invoices
          </Link>
          <h1 className="page-title">New invoice</h1>
        </div>
      </div>

      <div className="invoice-editor-grid">
        <section className="card card-padded invoice-form" aria-label="Invoice details">
          <FieldWrap label="Bill to">
            <ReferenceInput field={CUSTOMER_FIELD} value={customerId} onChange={setCustomerId} />
          </FieldWrap>
          <div className="invoice-form-row">
            <FieldWrap label="Due">
              <Select value={terms} onChange={(e) => setTerms(e.target.value)}>
                {TERMS.map(([v, label]) => (
                  <option key={v} value={v}>
                    {v === "" && customer ? `${label} (${customer.payment_terms_days ?? 0} days)` : label}
                  </option>
                ))}
              </Select>
            </FieldWrap>
            <FieldWrap label="Currency">
              <Select value={currency} onChange={(e) => setCurrency(e.target.value)}>
                {[...new Set([currency, ...CURRENCIES])].map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </Select>
            </FieldWrap>
          </div>

          <div className="invoice-lines" role="table" aria-label="Items">
            <div className="invoice-line invoice-line-head" role="row">
              <span>Item</span>
              <span>Qty</span>
              <span>Price</span>
              <span>Tax %</span>
              <span className="num">Amount</span>
              <span />
            </div>
            {lines.map((l, i) => (
              <div className="invoice-line" role="row" key={i}>
                <PickList aria-label="Item" free placeholder="Pick a product or type" value={l.description} onChange={(v) => pickProduct(i, v)} options={productOptions} />
                <Input aria-label="Quantity" inputMode="decimal" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} />
                <Input aria-label="Price before tax" inputMode="decimal" placeholder="0.00" value={l.unitPrice} onChange={(e) => setLine(i, { unitPrice: e.target.value, productId: l.productId })} />
                <Input aria-label="Tax percent" inputMode="decimal" value={l.taxPercent} onChange={(e) => setLine(i, { taxPercent: e.target.value })} />
                <span className="num">{money(lineCents(l).net + lineCents(l).tax)}</span>
                <button
                  type="button"
                  className="icon-btn"
                  aria-label="Remove this item"
                  onClick={() => setLines((cur) => (cur.length > 1 ? cur.filter((_, k) => k !== i) : cur))}
                >
                  <Icon name="close" size={14} />
                </button>
              </div>
            ))}
            <Button
              size="sm"
              className="btn-pill"
              onClick={() => setLines((cur) => [...cur, { description: "", quantity: "1", unitPrice: "", taxPercent: defaultTax }])}
            >
              <Icon name="plus" size={14} /> Add item
            </Button>
          </div>

          <details className="invoice-more">
            <summary>More options</summary>
            <FieldWrap label="Repeats">
              <Select value={repeats} onChange={(e) => setRepeats(e.target.value)}>
                <option value="">Doesn't repeat</option>
                <option value="weekly">Every week</option>
                <option value="monthly">Every month</option>
                <option value="yearly">Every year</option>
              </Select>
            </FieldWrap>
          </details>
        </section>

        <aside className="invoice-preview" aria-label="What the customer sees">
          <div className="invoice-paper">
            <div className="invoice-paper-head">
              <strong>{org.name || "Your business"}</strong>
              <span className="invoice-paper-kind">Invoice</span>
            </div>
            <div className="invoice-paper-meta">
              <div>
                <div className="field-label">Bill to</div>
                <div>{customer ? String(customer.name) : "—"}</div>
                {customer?.email ? <div className="field-label">{String(customer.email)}</div> : null}
              </div>
              <div style={{ textAlign: "right" }}>
                <div className="field-label">Issued {new Date().toLocaleDateString()}</div>
                <div className="field-label">Due {termsDays ? due.toLocaleDateString() : "on receipt"}</div>
              </div>
            </div>
            <table className="invoice-paper-lines">
              <tbody>
                {lines
                  .filter((l) => l.description.trim())
                  .map((l, i) => (
                    <tr key={i}>
                      <td>
                        {l.description} <span className="field-label">× {l.quantity || 1}</span>
                      </td>
                      <td className="num">{money(lineCents(l).net)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            <div className="invoice-paper-totals">
              <span>Subtotal</span>
              <span className="num">{money(totals.net)}</span>
              <span>Tax</span>
              <span className="num">{money(totals.tax)}</span>
              <strong>Total due</strong>
              <strong className="num">{money(totals.net + totals.tax)}</strong>
            </div>
          </div>
        </aside>
      </div>

      <div className="invoice-actions">
        {error ? <div className="error-banner" role="alert">{error}</div> : null}
        <Button variant="ghost" className="btn-pill" onClick={() => navigate("/invoicing/invoice")}>
          Cancel
        </Button>
        <Button className="btn-pill" disabled={!!busy} onClick={() => save(false)}>
          {busy === "draft" ? "Saving…" : "Save draft"}
        </Button>
        <Button variant="primary" className="btn-pill" disabled={!!busy} onClick={() => save(true)}>
          <Icon name="send" size={14} /> {busy === "send" ? "Sending…" : "Send invoice"}
        </Button>
      </div>
    </div>
  );
}

/** "New invoice" anywhere opens the full editor. */
export function GoToInvoiceEditor() {
  const navigate = useNavigate();
  useEffect(() => {
    navigate("/invoicing/invoice/new");
  }, [navigate]);
  return null;
}
