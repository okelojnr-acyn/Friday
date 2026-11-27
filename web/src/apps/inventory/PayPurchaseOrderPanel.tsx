import { fullDate } from "../../ui/resource/fieldFormat";
import { useState } from "react";
import { api, ApiError } from "../../lib/api";
import { formatMoney } from "../../lib/orgSettings";
import type { RecordRow } from "../../lib/types";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { FieldWrap, Input, Select } from "../../ui/Field";

const METHODS: [string, string][] = [
  ["mpesa", "M-Pesa"],
  ["bank_transfer", "Bank transfer"],
  ["cash", "Cash"],
  ["cheque", "Cheque"],
  ["card", "Card"],
  ["airtel", "Airtel Money"],
  ["pesapal", "Pesapal"],
];

interface PayPurchaseOrderPanelProps {
  record: RecordRow;
  onChanged: (record: RecordRow) => void;
}

/** Paying the supplier for goods received. Accounting books it against
 * what is owed (Accounts Payable) and the account the money left from. */
export function PayPurchaseOrderPanel({ record, onChanged }: PayPurchaseOrderPanelProps) {
  const [method, setMethod] = useState("mpesa");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (record.status !== "received") return null;
  const due = Number(record.total_due_cents ?? record.total_cost_cents ?? 0);

  if (record.paid_at) {
    const label = METHODS.find(([m]) => m === record.paid_method)?.[1] ?? String(record.paid_method);
    return (
      <Card style={{ marginTop: 12 }}>
        <div className="field-label">
          Paid {formatMoney(due)} on {fullDate(String(record.paid_at), false)} by {label}
          {record.paid_reference ? ` (${String(record.paid_reference)})` : ""}.
        </div>
      </Card>
    );
  }

  async function pay() {
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.post<RecordRow>(`/api/inventory/purchase_orders/${record.id}/pay`, { method, reference }));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not record the payment");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card style={{ marginTop: 12 }} className="form-grid">
      <div className="field-label">Owed to the supplier: {formatMoney(due)} (cost plus VAT)</div>
      {error ? <div className="error-banner">{error}</div> : null}
      <FieldWrap label="Paid by">
        <Select value={method} onChange={(e) => setMethod(e.target.value)}>
          {METHODS.map(([m, l]) => (
            <option key={m} value={m}>
              {l}
            </option>
          ))}
        </Select>
      </FieldWrap>
      <FieldWrap label="Reference (receipt or M-Pesa code)">
        <Input maxLength={80} value={reference} onChange={(e) => setReference(e.target.value)} />
      </FieldWrap>
      <div>
        <Button type="button" variant="primary" onClick={pay} disabled={busy}>
          {busy ? "Saving..." : `Mark paid (${formatMoney(due)})`}
        </Button>
      </div>
    </Card>
  );
}
