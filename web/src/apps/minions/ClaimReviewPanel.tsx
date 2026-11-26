import { useEffect, useState } from "react";
import { claimReceiptBlob, type ExpenseClaim } from "../../lib/minions";
import { formatMoney } from "../../lib/orgSettings";
import type { RecordRow } from "../../lib/types";
import { ClaimDecision, ClaimMarkPaid } from "./ClaimActions";

/** People > Expense claims, one claim: the receipt photo, who it waits on,
 * the decision (with its reason), and how it was paid. */
export function ClaimReviewPanel({
  record,
  onChanged,
}: {
  record: RecordRow;
  onChanged: (r: RecordRow) => void;
}) {
  const [photo, setPhoto] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const hasReceipt = Boolean(record.receipt_sha);
  const claim = record as unknown as ExpenseClaim;
  // Only a Minions that records payment methods sends paid_method; an older
  // one would ignore the method and pay by crypto, so it gets no choice.
  const knowsMethods = "paid_method" in record;
  const done = (c: ExpenseClaim) => onChanged(c as unknown as RecordRow);

  useEffect(() => {
    if (!hasReceipt) return;
    let url = "";
    claimReceiptBlob(record.id)
      .then((blob) => setPhoto((url = URL.createObjectURL(blob))))
      .catch((err) =>
        setError(
          err instanceof Error ? err.message : "Could not load the receipt",
        ),
      );
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [record.id, record.receipt_sha, hasReceipt]);

  return (
    <div className="card card-padded" style={{ marginTop: 16 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>
        {formatMoney(Number(claim.amount_cents) || 0, {
          currency: claim.currency || undefined,
        })}
        <span className="field-label">
          {" "}
          · {claim.reimburse === false ? (claim.paid_from === "petty_cash" ? "petty cash" : "business paid") : "pay back"}
        </span>
      </div>
      <p className="field-label">
        For: {claim.for_kind && claim.for_kind !== "daily" ? `${claim.for_kind} "${claim.for_label || claim.for_id}"` : "daily running"}
        {claim.category ? `, ${claim.category}` : ""}
        {claim.etims_invoice_no ? `, eTIMS ${claim.etims_invoice_no}` : ""}
        {!claim.receipt_sha && claim.no_receipt_reason ? `. No receipt: ${claim.no_receipt_reason}` : ""}
      </p>
      {claim.status === "submitted" && claim.waiting_on_name ? (
        <p className="field-label">Waiting for {claim.waiting_on_name}</p>
      ) : null}
      {claim.decided_by_name ? (
        <p className="field-label">
          {claim.status === "rejected" ? "Rejected" : "Decided"} by{" "}
          {claim.decided_by_name}
          {claim.decision_note ? `: ${claim.decision_note}` : ""}
        </p>
      ) : null}
      {claim.status === "paid" && claim.paid_method ? (
        <p className="field-label">
          Paid by {claim.paid_method === "mpesa" ? "M-Pesa" : claim.paid_method}
          {claim.paid_reference ? ` (${claim.paid_reference})` : ""}
        </p>
      ) : null}
      {error ? <div className="error-banner">{error}</div> : null}
      {!hasReceipt ? (
        <p className="field-label">No receipt photo on this claim.</p>
      ) : photo ? (
        <a href={photo} target="_blank" rel="noreferrer" title="Open full size">
          <img
            src={photo}
            alt={`Receipt for ${claim.description || "this claim"}`}
            style={{
              maxWidth: "100%",
              maxHeight: 420,
              borderRadius: 8,
              display: "block",
            }}
          />
        </a>
      ) : (
        <div className="spinner">Loading receipt…</div>
      )}
      {claim.status === "submitted" ? (
        <ClaimDecision claim={claim} onDone={done} />
      ) : null}
      {claim.status === "approved" && knowsMethods ? (
        <ClaimMarkPaid claim={claim} onDone={done} business={claim.reimburse === false} />
      ) : null}
    </div>
  );
}
