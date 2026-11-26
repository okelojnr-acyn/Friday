import { useState } from "react";
import { api, ApiError } from "../../lib/api";
import type { ExpenseClaim } from "../../lib/minions";
import { Button } from "../../ui/Button";
import { FieldWrap, Input, Select } from "../../ui/Field";

const errorText = (err: unknown, fallback: string) =>
  err instanceof ApiError ? err.message : fallback;

/** Approve, or reject with a reason (the claimant sees it and can fix the
 * claim). The server checks team, limit and "not your own". */
export function ClaimDecision({
  claim,
  onDone,
  base = "/api/minions/expense_claims",
}: {
  claim: { id: string };
  onDone: (c: ExpenseClaim) => void;
  /** Whose route: claims by default, or /api/minions/salary_advances. */
  base?: string;
}) {
  const [rejecting, setRejecting] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function decide(status: "approved" | "rejected") {
    setBusy(true);
    setError(null);
    try {
      onDone(
        await api.patch<ExpenseClaim>(
          `${base}/${claim.id}/status`,
          { status, note },
        ),
      );
    } catch (err) {
      setError(errorText(err, "Could not save the decision"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      {rejecting ? (
        <FieldWrap label="Why? They'll see this and can fix the claim" required>
          <Input
            autoFocus
            value={note}
            maxLength={300}
            placeholder="e.g. The receipt photo is blurry"
            onChange={(e) => setNote(e.target.value)}
          />
        </FieldWrap>
      ) : null}
      <div
        style={{
          display: "flex",
          gap: 8,
          justifyContent: "flex-end",
          flexWrap: "wrap",
        }}
      >
        {rejecting ? (
          <>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => setRejecting(false)}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={busy || !note.trim()}
              onClick={() => decide("rejected")}
            >
              Reject claim
            </Button>
          </>
        ) : (
          <>
            <Button
              size="sm"
              disabled={busy}
              onClick={() => setRejecting(true)}
            >
              Reject
            </Button>
            <Button
              size="sm"
              variant="primary"
              disabled={busy}
              onClick={() => decide("approved")}
            >
              Approve
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

const METHODS = [
  ["mpesa", "M-Pesa", "M-Pesa code"],
  ["bank", "Bank transfer", "Bank reference"],
  ["cash", "Cash", "Note (optional)"],
  ["crypto", "Crypto wallet (sends it now)", ""],
] as const;
type Method = (typeof METHODS)[number][0];

/** Records how an approved pay-back claim was paid; the books take it from
 * that account. Crypto sends the money through the wallet; the others
 * record a payment already made. */
export function ClaimMarkPaid({
  claim,
  onDone,
  base = "/api/minions/expense_claims",
  business = false,
}: {
  claim: { id: string };
  onDone: (c: ExpenseClaim) => void;
  /** Whose route: claims by default, or /api/minions/salary_advances. */
  base?: string;
  /** The business's own money paid it: confirm how (books it); no wallet. */
  business?: boolean;
}) {
  const [method, setMethod] = useState<Method>("mpesa");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [, , refLabel] = METHODS.find(([m]) => m === method)!;
  const needsRef = method === "mpesa" || method === "bank";

  async function pay() {
    setBusy(true);
    setError(null);
    try {
      onDone(
        await api.post<ExpenseClaim>(
          `${base}/${claim.id}/pay`,
          { method, reference },
        ),
      );
    } catch (err) {
      setError(errorText(err, "Could not record the payment"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="form-grid" style={{ marginTop: 12 }}>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <FieldWrap label={business ? "The business paid from" : "Paid by"}>
        <Select
          value={method}
          onChange={(e) => setMethod(e.target.value as Method)}
        >
          {METHODS.filter(([m]) => !business || m !== "crypto").map(([m, label]) => (
            <option key={m} value={m}>
              {label}
            </option>
          ))}
        </Select>
      </FieldWrap>
      {refLabel ? (
        <FieldWrap label={refLabel} required={needsRef}>
          <Input
            value={reference}
            maxLength={60}
            onChange={(e) => setReference(e.target.value)}
          />
        </FieldWrap>
      ) : null}
      <div>
        <Button
          variant="primary"
          disabled={busy || (needsRef && !reference.trim())}
          onClick={pay}
        >
          {business ? "Confirm the business paid" : method === "crypto" ? "Send payment" : "Mark as paid"}
        </Button>
      </div>
    </div>
  );
}
