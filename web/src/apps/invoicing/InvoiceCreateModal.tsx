import { useState } from "react";
import { Modal } from "../../ui/Modal";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { FieldWrap, Input, Select } from "../../ui/Field";
import { ReferenceInput } from "../../ui/resource/ReferenceInput";
import { amountInputToCents } from "../../ui/resource/fieldFormat";
import { createRecord } from "../../lib/resourceApi";
import { ApiError } from "../../lib/api";
import type { FieldSpec, RecordRow } from "../../lib/types";

interface Line {
  description: string;
  quantity: string;
  unitPrice: string;
  /** Percent as typed (e.g. "16" for 16% VAT); sent as basis points. */
  taxPercent: string;
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

function emptyLine(taxPercent = ""): Line {
  return { description: "", quantity: "1", unitPrice: "", taxPercent };
}

/** Mirrors InvoiceLine.total_cents / tax_cents on the server (net is
 * qty x price, tax is floor(net x bp / 10000)) so the preview matches
 * what the invoice will actually say. */
function lineCents(l: Line): { net: number; tax: number } {
  const net = Math.trunc((Number(l.quantity) || 0) * amountInputToCents(l.unitPrice || "0"));
  const bp = Math.round((Number(l.taxPercent) || 0) * 100);
  return { net, tax: Math.floor((net * bp) / 10000) };
}

function money(cents: number, currency: string): string {
  return `${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${currency}`;
}

interface DocumentCreateModalProps {
  onClose: () => void;
  onSaved: (record: RecordRow) => void;
  kind?: "invoice" | "quote";
}

/** Create screen for invoices *and* quotes -- the same document shape
 * (customer, currency, lines with tax), see apps/invoicing's
 * 0009_quotes.sql. The generic FormView only ever exposes "status" on
 * these (no general PATCH -- see UPDATE_PATH_OVERRIDES in resourceApi.ts),
 * so it can't be the create screen: a customer and taxed line items are
 * what actually make the document.
 *
 * Per-line tax % was missing entirely before 2026-11-10 -- every manual
 * invoice went out at 0% tax, unusable for a VAT-registered business.
 * Defaults stay neutral (USD, 0%) until per-org defaults exist (the P4
 * setup wizard in ROADMAP.md). */
export function InvoiceCreateModal({ onClose, onSaved, kind = "invoice" }: DocumentCreateModalProps) {
  const isQuote = kind === "quote";
  const [customerId, setCustomerId] = useState<unknown>(null);
  const [currency, setCurrency] = useState("USD");
  const [recurringInterval, setRecurringInterval] = useState("");
  const [validDays, setValidDays] = useState("30");
  const [defaultTax, setDefaultTax] = useState("");
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const totals = lines.reduce(
    (acc, l) => {
      const { net, tax } = lineCents(l);
      return { net: acc.net + net, tax: acc.tax + tax };
    },
    { net: 0, tax: 0 },
  );

  function updateLine(i: number, patch: Partial<Line>) {
    setLines((cur) => cur.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }

  function addLine() {
    setLines((cur) => [...cur, emptyLine(defaultTax)]);
  }

  function removeLine(i: number) {
    setLines((cur) => (cur.length > 1 ? cur.filter((_, idx) => idx !== i) : cur));
  }

  async function onSubmit() {
    const validLines = lines.filter((l) => l.description.trim());
    if (validLines.length === 0) {
      setError("Add at least one line");
      return;
    }
    if (validLines.some((l) => Number(l.taxPercent) < 0 || Number(l.taxPercent) > 100)) {
      setError("Tax must be between 0% and 100%");
      return;
    }
    setSubmitting(true);
    setError(null);
    const payloadLines = validLines.map((l) => ({
      description: l.description,
      quantity: Number(l.quantity) || 1,
      unit_price_cents: amountInputToCents(l.unitPrice || "0"),
      tax_rate_bp: Math.round((Number(l.taxPercent) || 0) * 100),
    }));
    try {
      const saved = isQuote
        ? await createRecord("invoicing", "quote", {
            customer_id: customerId || null,
            currency,
            valid_days: Number(validDays) || 30,
            lines: payloadLines,
          })
        : await createRecord("invoicing", "invoice", {
            customer_id: customerId || null,
            currency,
            recurring_interval: recurringInterval,
            lines: payloadLines,
          });
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : `Could not create ${kind}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title={isQuote ? "New Quote" : "New Invoice"}
      onClose={onClose}
      footer={
        <>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="button" variant="primary" onClick={onSubmit} disabled={submitting}>
            {submitting ? "Creating..." : "Create"}
          </Button>
        </>
      }
    >
      {error ? <div className="error-banner">{error}</div> : null}
      <FieldWrap label="Customer">
        <ReferenceInput field={CUSTOMER_FIELD} value={customerId} onChange={setCustomerId} />
      </FieldWrap>
      <FieldWrap label="Currency">
        <Input
          value={currency}
          onChange={(e) => setCurrency(e.target.value.toUpperCase().slice(0, 3))}
          style={{ width: 90 }}
        />
      </FieldWrap>
      {isQuote ? (
        <FieldWrap label="Valid for (days)">
          <Input
            type="number"
            min={1}
            max={365}
            value={validDays}
            onChange={(e) => setValidDays(e.target.value)}
            style={{ width: 90 }}
          />
        </FieldWrap>
      ) : (
        <FieldWrap label="Repeats">
          <Select value={recurringInterval} onChange={(e) => setRecurringInterval(e.target.value)} style={{ width: 140 }}>
            <option value="">Does not repeat</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="yearly">Yearly</option>
          </Select>
        </FieldWrap>
      )}
      <FieldWrap label="Default tax % for new lines">
        <Input
          type="number"
          step="0.01"
          min={0}
          max={100}
          placeholder="0"
          value={defaultTax}
          onChange={(e) => setDefaultTax(e.target.value)}
          style={{ width: 90 }}
        />
      </FieldWrap>

      <div className="invoice-lines">
        <span className="field-label">Lines (description · qty · unit price · tax %)</span>
        {lines.map((line, i) => (
          <div className="invoice-line-row" key={i}>
            <Input
              placeholder="Description"
              value={line.description}
              onChange={(e) => updateLine(i, { description: e.target.value })}
            />
            <Input
              type="number"
              placeholder="Qty"
              aria-label="Quantity"
              value={line.quantity}
              onChange={(e) => updateLine(i, { quantity: e.target.value })}
              style={{ width: 64 }}
            />
            <Input
              type="number"
              step="0.01"
              placeholder="Price"
              aria-label="Unit price"
              value={line.unitPrice}
              onChange={(e) => updateLine(i, { unitPrice: e.target.value })}
              style={{ width: 96 }}
            />
            <Input
              type="number"
              step="0.01"
              placeholder="Tax %"
              aria-label="Tax percent"
              value={line.taxPercent}
              onChange={(e) => updateLine(i, { taxPercent: e.target.value })}
              style={{ width: 72 }}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => removeLine(i)}
              disabled={lines.length === 1}
              aria-label="Remove line"
            >
              <Icon name="close" size={14} />
            </Button>
          </div>
        ))}
        <Button type="button" variant="secondary" size="sm" onClick={addLine}>
          <Icon name="plus" size={14} /> Add line
        </Button>
      </div>

      <div className="invoice-total-row">
        <span>Subtotal</span>
        <span>{money(totals.net, currency)}</span>
      </div>
      <div className="invoice-total-row">
        <span>Tax</span>
        <span>{money(totals.tax, currency)}</span>
      </div>
      <div className="invoice-total-row">
        <span>Total</span>
        <span>{money(totals.net + totals.tax, currency)}</span>
      </div>
    </Modal>
  );
}

/** Registered as the "invoicing.quote" custom create screen. */
export function QuoteCreateModal(props: Omit<DocumentCreateModalProps, "kind">) {
  return <InvoiceCreateModal {...props} kind="quote" />;
}
