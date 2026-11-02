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
  productId: unknown;
  description: string;
  quantity: string;
  unitCost: string;
}

const SUPPLIER_FIELD: FieldSpec = {
  name: "supplier_id",
  label: "Supplier",
  type: "reference",
  required: false,
  options: null,
  reference: "inventory.supplier",
  listVisible: true,
  formVisible: true,
};

const PRODUCT_FIELD: FieldSpec = {
  name: "product_id",
  label: "Product",
  type: "reference",
  required: false,
  options: null,
  reference: "inventory.product",
  listVisible: true,
  formVisible: true,
};

function emptyLine(): Line {
  return { productId: null, description: "", quantity: "1", unitCost: "" };
}

interface PurchaseOrderCreateModalProps {
  onClose: () => void;
  onSaved: (record: RecordRow) => void;
}

/** Same shape as InvoiceCreateModal, same reason: a supplier and line
 * items up front aren't a flat field list, so this doesn't go through
 * the generic FormView either (see ARCHITECTURE.md's schema-driven UI
 * contract on when a resource earns a hand-written create screen). */
export function PurchaseOrderCreateModal({ onClose, onSaved }: PurchaseOrderCreateModalProps) {
  const [supplierId, setSupplierId] = useState<unknown>(null);
  const [lines, setLines] = useState<Line[]>([emptyLine()]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const totalCents = lines.reduce(
    (sum, l) => sum + (Number(l.quantity) || 0) * amountInputToCents(l.unitCost || "0"),
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
    const validLines = lines.filter((l) => l.productId || l.description.trim());
    if (validLines.length === 0) {
      setError("Add at least one line");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const saved = await createRecord("inventory", "purchase_order", {
        supplier_id: supplierId || null,
        lines: validLines.map((l) => ({
          product_id: l.productId || null,
          description: l.description,
          quantity: Number(l.quantity) || 1,
          unit_cost_cents: amountInputToCents(l.unitCost || "0"),
        })),
      });
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not create purchase order");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal
      title="New Purchase Order"
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
      <FieldWrap label="Supplier">
        <ReferenceInput field={SUPPLIER_FIELD} value={supplierId} onChange={setSupplierId} />
      </FieldWrap>

      <div className="invoice-lines">
        <span className="field-label">Lines</span>
        {lines.map((line, i) => (
          <div className="invoice-line-row" key={i}>
            <ReferenceInput
              field={PRODUCT_FIELD}
              value={line.productId}
              onChange={(v) => updateLine(i, { productId: v })}
            />
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
              placeholder="Unit cost"
              value={line.unitCost}
              onChange={(e) => updateLine(i, { unitCost: e.target.value })}
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
        <span>Total cost</span>
        <span>${(totalCents / 100).toFixed(2)}</span>
      </div>
    </Modal>
  );
}
