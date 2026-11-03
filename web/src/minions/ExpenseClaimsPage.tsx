import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../lib/api";
import { fetchMyExpenseClaims, submitExpenseClaim, type ExpenseClaim } from "../lib/minions";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import { Badge, statusTone } from "../ui/Badge";

export function ExpenseClaimsPage() {
  const [claims, setClaims] = useState<ExpenseClaim[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [receiptUrl, setReceiptUrl] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetchMyExpenseClaims()
      .then(setClaims)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load expense claims"));
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const amountCents = Math.round(Number.parseFloat(amount || "0") * 100);
    if (!description.trim() || !Number.isFinite(amountCents) || amountCents <= 0) {
      setError("A description and a positive amount are required");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const claim = await submitExpenseClaim({ description: description.trim(), amount_cents: amountCents, receipt_url: receiptUrl.trim() });
      setClaims((cur) => [claim, ...(cur ?? [])]);
      setDescription("");
      setAmount("");
      setReceiptUrl("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not submit claim");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Expense Claims</h1>
      </div>

      {error ? <div className="error-banner" style={{ marginBottom: 16 }}>{error}</div> : null}

      <Card style={{ marginBottom: 16 }}>
        <div className="field-label" style={{ marginBottom: 10 }}>
          Submit a new claim
        </div>
        <form onSubmit={onSubmit} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <FieldWrap label="Description" required>
            <Input value={description} onChange={(e) => setDescription(e.target.value)} style={{ width: 220 }} />
          </FieldWrap>
          <FieldWrap label="Amount" required>
            <Input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              inputMode="decimal"
              placeholder="0.00"
              style={{ width: 100 }}
            />
          </FieldWrap>
          <FieldWrap label="Receipt URL">
            <Input value={receiptUrl} onChange={(e) => setReceiptUrl(e.target.value)} style={{ width: 200 }} />
          </FieldWrap>
          <Button type="submit" disabled={submitting}>
            {submitting ? "Submitting..." : "Submit"}
          </Button>
        </form>
      </Card>

      {claims === null ? (
        <div className="page spinner">Loading...</div>
      ) : claims.length === 0 ? (
        <div className="empty-state">No expense claims submitted yet.</div>
      ) : (
        claims.map((c) => (
          <Card key={c.id} style={{ marginBottom: 10 }}>
            <div className="pos-totals-row">
              <span>
                {c.description}
                <span className="field-label" style={{ marginLeft: 8 }}>
                  {new Date(c.submitted_at).toLocaleDateString()}
                </span>
              </span>
              <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span>${(c.amount_cents / 100).toFixed(2)}</span>
                <Badge tone={statusTone(c.status)}>{c.status}</Badge>
              </span>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
