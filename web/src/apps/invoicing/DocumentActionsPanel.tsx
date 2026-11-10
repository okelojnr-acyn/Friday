import { useState } from "react";
import { api, ApiError } from "../../lib/api";
import { amountInputToCents } from "../../ui/resource/fieldFormat";
import { Button } from "../../ui/Button";
import { Input, Select } from "../../ui/Field";
import type { RecordRow } from "../../lib/types";

// Mirrors PAYMENT_METHODS in apps/invoicing/app/models.py minus the ones
// only set by automated flows (pos, refund, pesapal, card via Stripe).
const MANUAL_METHODS: [string, string][] = [
  ["bank_transfer", "Bank transfer"],
  ["cash", "Cash"],
  ["card", "Card (taken elsewhere)"],
  ["other", "Other (e.g. M-Pesa)"],
];

function money(cents: number, currency: string): string {
  return `${currency} ${(cents / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

interface Props {
  kind: "invoice" | "quote";
  record: RecordRow;
  /** Called with the updated/created document so the list refreshes. */
  onChanged: (record: RecordRow) => void;
}

/** The quote-to-cash actions the generic FormView can't express:
 * converting an accepted quote into an invoice, and recording a full or
 * partial payment against an invoice's balance (bank transfer, cash,
 * M-Pesa...). Same targeted special-case shape as PayWithCardPanel. */
export function DocumentActionsPanel({ kind, record, onChanged }: Props) {
  const currency = String(record.currency ?? "USD");
  const balance = Number(record.balance_cents ?? 0);
  const [amount, setAmount] = useState(balance > 0 ? (balance / 100).toFixed(2) : "");
  const [method, setMethod] = useState("bank_transfer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function run(fn: () => Promise<RecordRow>, success: (r: RecordRow) => string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await fn();
      setNotice(success(r));
      onChanged(r);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  if (kind === "quote") {
    const status = String(record.status ?? "");
    const expired = record.valid_until ? new Date(String(record.valid_until)) < new Date() : false;
    if (status === "accepted" || status === "declined") {
      return (
        <div className="card card-padded" style={{ marginTop: 12 }}>
          <div className="field-label">This quote is {status}.</div>
        </div>
      );
    }
    return (
      <div className="card card-padded" style={{ marginTop: 12 }}>
        <div className="field-label" style={{ marginBottom: 8 }}>
          Customer accepted? Turn this quote into a draft invoice with the same lines.
        </div>
        {expired ? <div className="error-banner">This quote has expired -- issue a new one.</div> : null}
        {error ? <div className="error-banner">{error}</div> : null}
        {notice ? <div className="field-label">{notice}</div> : null}
        <Button
          type="button"
          disabled={busy || expired}
          onClick={() => {
            let invoiceNumber = "";
            return run(
              async () => {
                const inv = await api.post<RecordRow>(`/api/invoicing/quotes/${record.id}/convert`);
                invoiceNumber = String(inv.number);
                // Hand the *quote* (now "accepted") back to the Quotes list,
                // not the new invoice -- ResourcePage's onSaved upserts by id
                // and would otherwise drop an invoice into the quotes list.
                return api.get<RecordRow>(`/api/invoicing/quotes/${record.id}`);
              },
              () => `Created draft invoice ${invoiceNumber} -- find it under Invoices.`,
            );
          }}
        >
          {busy ? "Converting..." : "Convert to invoice"}
        </Button>
      </div>
    );
  }

  if (balance <= 0 || record.status === "void" || record.status === "draft") {
    return record.status === "draft" ? (
      <div className="card card-padded" style={{ marginTop: 12 }}>
        <div className="field-label">Set the status to "sent" to issue this invoice and start collecting payment.</div>
      </div>
    ) : null;
  }

  return (
    <div className="card card-padded" style={{ marginTop: 12 }}>
      <div className="field-label" style={{ marginBottom: 8 }}>
        Record a payment -- {money(balance, currency)} outstanding
        {record.is_overdue ? ` · overdue ${String(record.days_overdue)} days` : ""}
      </div>
      {error ? <div className="error-banner">{error}</div> : null}
      {notice ? <div className="field-label">{notice}</div> : null}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <Input
          type="number"
          step="0.01"
          min={0}
          aria-label="Amount"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          style={{ width: 120 }}
        />
        <Select aria-label="Method" value={method} onChange={(e) => setMethod(e.target.value)} style={{ width: 190 }}>
          {MANUAL_METHODS.map(([v, label]) => (
            <option key={v} value={v}>
              {label}
            </option>
          ))}
        </Select>
        <Button
          type="button"
          disabled={busy || amountInputToCents(amount || "0") <= 0}
          onClick={() =>
            run(
              () =>
                api.post<RecordRow>(`/api/invoicing/invoices/${record.id}/payments`, {
                  amount_cents: amountInputToCents(amount),
                  method,
                }),
              (inv) =>
                Number(inv.balance_cents) <= 0
                  ? "Paid in full."
                  : `Payment recorded -- ${money(Number(inv.balance_cents), currency)} still outstanding.`,
            )
          }
        >
          {busy ? "Saving..." : "Record payment"}
        </Button>
      </div>
    </div>
  );
}
