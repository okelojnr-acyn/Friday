import { useState } from "react";
import { Modal } from "../../ui/Modal";
import { Button } from "../../ui/Button";
import { Icon } from "../../ui/Icon";
import { FieldWrap, Input } from "../../ui/Field";
import { ReferenceInput } from "../../ui/resource/ReferenceInput";
import { amountInputToCents } from "../../ui/resource/fieldFormat";
import { createRecord } from "../../lib/resourceApi";
import { ApiError } from "../../lib/api";
import type { FieldSpec, RecordRow } from "../../lib/types";

interface Line {
  description: string;
  quantity: string;
  unitPrice: string;
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

function emptyLine(): Line {
  return { description: "", quantity: "1", unitPrice: "" };
}

interface InvoiceCreateModalProps {
  onClose: () => void;
  onSaved: (record: RecordRow) => void;
}

/** The generic FormView only ever exposes "status" on an invoice (there's
 * no general PATCH /invoices/{id} -- see UPDATE_PATH_OVERRIDES in
 * resourceApi.ts), so it can't be the create screen too: a customer and
 * line items are what actually make an invoice. Same precedent as the
 * POS register -- a custom screen for the one workflow that doesn't fit
 * list/kanban/form, not a generic line-items builder nothing else needs
 * yet. */
export function InvoiceCreateModal({ onClose, onSaved }: InvoiceCreateModalProps) {
  const [customerId, setCustomerId] = useState<unknown>(null);
  const [currency, setCurrency] = useState("USD");
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const totalCents = lines.reduce(
    (sum, l) => sum + (Number(l.quantity) || 0) * amountInputToCents(l.unitPrice || "0"),
    0,
  );

  function updateLine(i: number, patch: Partial<Line>) {
    setLines((cur) => cur.map((l, idx) => (idx === i ? { ...l, ...patch } : l)));
  }

  function addLine() {
    setLines((cur) => [...cur, emptyLine()]);
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
    setSubmitting(true);
    setError(null);
    try {
      const saved = await createRecord("invoicing", "invoice", {
        customer_id: customerId || null,
        currency,
        lines: validLines.map((l) => ({
          description: l.description,
          quantity: Number(l.quantity) || 1,
          unit_price_cents: amountInputToCents(l.unitPrice || "0"),
        })),
      });
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create invoice");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title="New Invoice"
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

      <div className="invoice-lines">
        <span className="field-label">Lines</span>
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
              value={line.quantity}
              onChange={(e) => updateLine(i, { quantity: e.target.value })}
              style={{ width: 64 }}
            />
            <Input
              type="number"
              step="0.01"
              placeholder="Price"
              value={line.unitPrice}
              onChange={(e) => updateLine(i, { unitPrice: e.target.value })}
              style={{ width: 96 }}
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
        <span>Total</span>
        <span>${(totalCents / 100).toFixed(2)}</span>
      </div>
    </Modal>
  );
}
