import { useEffect, useState } from "react";
import { api, ApiError } from "../../lib/api";
import { claimReceiptBlob } from "../../lib/minions";
import { formatMoney } from "../../lib/orgSettings";
import type { RecordRow } from "../../lib/types";
import { Button } from "../../ui/Button";

/** People > Expense claims, one claim: the receipt photo and, while it
 * waits, Approve / Reject (the server checks team, limit and "not your own"). */
export function ClaimReviewPanel({
  record,
  onChanged,
}: {
  record: RecordRow;
  onChanged: (r: RecordRow) => void;
}) {
  const [photo, setPhoto] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hasReceipt = Boolean(record.receipt_sha);

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

  async function decide(status: "approved" | "rejected") {
    setBusy(true);
    setError(null);
    try {
      onChanged(
        await api.patch<RecordRow>(
          `/api/minions/expense_claims/${record.id}/status`,
          { status },
        ),
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card card-padded" style={{ marginTop: 16 }}>
      <div style={{ fontWeight: 600, marginBottom: 8 }}>
        {formatMoney(Number(record.amount_cents) || 0, {
          currency: String(record.currency || "") || undefined,
        })}
        <span className="field-label">
          {" "}
          · {record.reimburse === false ? "business paid" : "pay back"}
        </span>
      </div>
      {error ? <div className="error-banner">{error}</div> : null}
      {!hasReceipt ? (
        <p className="field-label">No receipt photo on this claim.</p>
      ) : photo ? (
        <a href={photo} target="_blank" rel="noreferrer" title="Open full size">
          <img
            src={photo}
            alt={`Receipt for ${String(record.description ?? "this claim")}`}
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
      {record.status === "submitted" ? (
        <div
          style={{
            display: "flex",
            gap: 8,
            justifyContent: "flex-end",
            marginTop: 12,
          }}
        >
          <Button disabled={busy} onClick={() => decide("rejected")}>
            Reject
          </Button>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() => decide("approved")}
          >
            Approve
          </Button>
        </div>
      ) : null}
    </div>
  );
}
