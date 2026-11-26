import { useState } from "react";
import { api, ApiError } from "../../lib/api";
import type { RecordRow } from "../../lib/types";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";

const NAME: Record<string, string> = { paystack: "Paystack", stripe: "Stripe", pesapal: "Pesapal" };

/** A sent invoice's pay request: which provider asked the customer to
 * pay, and asking again (the last request is cancelled). Friday checks
 * the provider until it's paid; nothing to do here but wait. */
export function PayRequestPanel({ record, onChanged }: { record: RecordRow; onChanged: (r: RecordRow) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (record.status !== "sent" || record.pay_request_provider === undefined) return null;
  const provider = NAME[String(record.pay_request_provider)] ?? "";
  const url = String(record.pay_request_url ?? "");

  async function again() {
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.post<RecordRow>(`/api/invoicing/invoices/${record.id}/pay-request`));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not ask again");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card style={{ marginTop: 12 }}>
      <div className="form-grid">
        <div className="field-label">
          {provider
            ? `${provider} asked the customer to pay${url ? "" : " by email"}; it's marked paid here once ${provider} says so.`
            : "No pay request yet: connect Paystack, Stripe or Pesapal and give the customer an email, then ask."}
        </div>
        {url ? (
          <a className="field-label" href={url} target="_blank" rel="noreferrer">
            {url}
          </a>
        ) : null}
        {error ? (
          <div className="error-banner" role="alert">
            {error}
          </div>
        ) : null}
        <div>
          <Button disabled={busy} onClick={again}>
            {provider ? "Ask again" : "Ask the customer to pay"}
          </Button>
        </div>
      </div>
    </Card>
  );
}
