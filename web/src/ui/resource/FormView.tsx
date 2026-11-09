import { useState, type FormEvent } from "react";
import type { RecordRow, ResourceSpec } from "../../lib/types";
import { ApiError } from "../../lib/api";
import { createRecord, updateRecord } from "../../lib/resourceApi";
import { Modal } from "../Modal";
import { Button } from "../Button";
import { FieldWrap } from "../Field";
import { FieldInput } from "./FieldInput";
import { SmartButtons } from "./SmartButtons";
import { PayWithCardPanel } from "../../apps/invoicing/PayWithCardPanel";
import { CreatePurchaseOrderPanel } from "../../apps/inventory/CreatePurchaseOrderPanel";
import { amountInputToCents, centsToAmountInput, toDateInputValue, toDatetimeInputValue } from "./fieldFormat";

interface FormViewProps {
  spec: ResourceSpec;
  app: string;
  schema: ResourceSpec[];
  record?: RecordRow;
  onClose: () => void;
  onSaved: (record: RecordRow) => void;
}

export function initialValues(spec: ResourceSpec, record?: RecordRow): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const field of spec.fields) {
    if (!field.formVisible) continue;
    const raw = record ? record[field.name] : undefined;
    switch (field.type) {
      case "currency":
        values[field.name] = raw === undefined ? "" : centsToAmountInput(raw);
        break;
      case "date":
        values[field.name] = toDateInputValue(raw);
        break;
      case "datetime":
        values[field.name] = toDatetimeInputValue(raw);
        break;
      case "boolean":
        values[field.name] = Boolean(raw);
        break;
      case "reference":
        values[field.name] = raw ?? null;
        break;
      default:
        values[field.name] = raw ?? "";
    }
  }
  return values;
}

export function toWireBody(spec: ResourceSpec, values: Record<string, unknown>): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const field of spec.fields) {
    if (!field.formVisible) continue;
    const v = values[field.name];
    if (field.type === "currency") {
      body[field.name] = amountInputToCents(String(v ?? "0"));
    } else if (field.type === "number") {
      body[field.name] = v === "" ? 0 : Number(v);
    } else if (field.type === "reference") {
      body[field.name] = v || null;
    } else if (field.type === "date" || field.type === "datetime") {
      // An empty <input type="date"> is "" -- a bare empty string isn't a
      // valid value for an Optional[datetime] field server-side, so an
      // unset date must become null, not "".
      body[field.name] = v || null;
    } else {
      body[field.name] = v;
    }
  }
  return body;
}

export function FormView({ spec, app, schema, record, onClose, onSaved }: FormViewProps) {
  const [values, setValues] = useState<Record<string, unknown>>(() => initialValues(spec, record));
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const fields = spec.fields.filter((f) => f.formVisible);
  const isEdit = Boolean(record);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const body = toWireBody(spec, values);
      const saved = isEdit
        ? await updateRecord(app, spec.name, record!.id, body)
        : await createRecord(app, spec.name, body);
      onSaved(saved);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal title={isEdit ? spec.label : `New ${spec.label}`} onClose={onClose}>
      <form onSubmit={onSubmit} className="form-grid">
        {isEdit ? <SmartButtons app={app} schema={schema} spec={spec} recordId={record!.id} /> : null}
        {error ? <div className="error-banner">{error}</div> : null}
        {fields.length === 0 ? (
          <div className="field-label">Nothing on this record is editable here.</div>
        ) : (
          fields.map((field) => (
            <FieldWrap key={field.name} label={field.label} required={field.required}>
              <FieldInput
                field={field}
                value={values[field.name]}
                onChange={(v) => setValues((cur) => ({ ...cur, [field.name]: v }))}
              />
            </FieldWrap>
          ))
        )}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" disabled={submitting || fields.length === 0}>
            {submitting ? "Saving..." : "Save"}
          </Button>
        </div>
      </form>
      {isEdit && app === "invoicing" && spec.name === "invoice" ? (
        <PayWithCardPanel
          invoiceId={record!.id}
          balanceCents={Number(record!.balance_cents ?? 0)}
          currency={String(record!.currency ?? "USD")}
        />
      ) : null}
      {isEdit && app === "inventory" && spec.name === "product" ? (
        <CreatePurchaseOrderPanel
          productId={record!.id}
          onHandQty={Number(record!.on_hand_qty ?? 0)}
          reorderPoint={Number(record!.reorder_point ?? 0)}
        />
      ) : null}
    </Modal>
  );
}
