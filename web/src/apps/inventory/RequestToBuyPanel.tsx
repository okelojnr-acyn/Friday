import { useState } from "react";
import { api, ApiError } from "../../lib/api";
import type { RecordRow } from "../../lib/types";
import { Button } from "../../ui/Button";
import { Card } from "../../ui/Card";
import { FieldWrap, Input } from "../../ui/Field";

/** A request to buy (spending plan part D): a draft over your ask-first
 * amount is sent for approval; someone else approves it or sends it back
 * with a reason; then it's ordered. The server checks who may and limits. */
export function RequestToBuyPanel({ record, onChanged }: { record: RecordRow; onChanged: (r: RecordRow) => void }) {
  const [note, setNote] = useState("");
  const [sendingBack, setSendingBack] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = String(record.status);
  if (!["draft", "requested", "approved"].includes(status)) return null;

  async function move(to: string) {
    setBusy(true);
    setError(null);
    try {
      onChanged(await api.patch<RecordRow>(`/api/inventory/purchase_orders/${record.id}/status`, { status: to, note: note.trim() }));
      setSendingBack(false);
      setNote("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save that");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card style={{ marginTop: 12 }}>
      <div className="form-grid">
        <div className="field-label">
          {status === "draft"
            ? record.decision_note
              ? `Sent back by ${record.decided_by_name}: ${record.decision_note}`
              : "Over your amount to order straight away? Send it for approval first."
            : status === "requested"
              ? `Waiting for approval, asked by ${record.requested_by_name}.`
              : `Approved by ${record.decided_by_name}. It can be ordered.`}
        </div>
        {error ? (
          <div className="error-banner" role="alert">
            {error}
          </div>
        ) : null}
        {sendingBack ? (
          <FieldWrap label="Why it's sent back" required>
            <Input autoFocus value={note} maxLength={300} placeholder="e.g. Get a second quote" onChange={(e) => setNote(e.target.value)} />
          </FieldWrap>
        ) : null}
        <div className="minions-actions">
          {status === "draft" ? (
            <Button disabled={busy} onClick={() => move("requested")}>
              Send for approval
            </Button>
          ) : null}
          {status === "requested" && !sendingBack ? (
            <>
              <Button disabled={busy} onClick={() => setSendingBack(true)}>
                Send back
              </Button>
              <Button variant="primary" disabled={busy} onClick={() => move("approved")}>
                Approve
              </Button>
            </>
          ) : null}
          {sendingBack ? (
            <>
              <Button variant="ghost" onClick={() => setSendingBack(false)}>
                Cancel
              </Button>
              <Button disabled={busy || !note.trim()} onClick={() => move("draft")}>
                Send back
              </Button>
            </>
          ) : null}
          {status === "approved" ? (
            <Button variant="primary" disabled={busy} onClick={() => move("ordered")}>
              Mark as ordered
            </Button>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
