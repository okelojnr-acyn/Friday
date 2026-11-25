import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../lib/api";
import {
  fetchMyExpenseClaims,
  openClaimReceipt,
  submitExpenseClaim,
  uploadClaimReceipt,
  withdrawExpenseClaim,
  type ExpenseClaim,
} from "../lib/minions";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";
import { Badge, statusTone } from "../ui/Badge";
import { formatMoney, useOrgSettings } from "../lib/orgSettings";

export function ExpenseClaimsPage() {
  const [claims, setClaims] = useState<ExpenseClaim[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoKey, setPhotoKey] = useState(0); // resets the file input
  // Who paid varies person to person (owner, 2026-11-22), so always ask.
  const [whoPaid, setWhoPaid] = useState<"" | "me" | "business">("");
  const [submitting, setSubmitting] = useState(false);
  // Claims are in the business's currency (Minions would otherwise store USD).
  const { currency } = useOrgSettings();

  useEffect(() => {
    fetchMyExpenseClaims()
      .then(setClaims)
      .catch((err) =>
        setError(
          err instanceof ApiError
            ? err.message
            : "Could not load expense claims",
        ),
      );
  }, []);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const amountCents = Math.round(Number.parseFloat(amount || "0") * 100);
    if (
      !description.trim() ||
      !Number.isFinite(amountCents) ||
      amountCents <= 0
    ) {
      setError("A description and a positive amount are required");
      return;
    }
    if (!whoPaid) {
      setError("Say who paid: you (pay you back) or the business");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      let claim = await submitExpenseClaim({
        description: description.trim(),
        amount_cents: amountCents,
        currency,
        reimburse: whoPaid === "me",
      });
      if (photo) {
        try {
          claim = await uploadClaimReceipt(claim.id, photo);
        } catch (err) {
          setError(
            `Claim saved, but the receipt didn't upload: ${err instanceof Error ? err.message : "try again"}`,
          );
        }
      }
      setClaims((cur) => [claim, ...(cur ?? [])]);
      setDescription("");
      setAmount("");
      setPhoto(null);
      setPhotoKey((k) => k + 1);
      setWhoPaid("");
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "Could not submit claim",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1 className="page-title">Expense Claims</h1>
      </div>

      {error ? (
        <div className="error-banner" style={{ marginBottom: 16 }}>
          {error}
        </div>
      ) : null}

      <Card style={{ marginBottom: 16 }}>
        <div className="field-label" style={{ marginBottom: 10 }}>
          Submit a new claim
        </div>
        <form
          onSubmit={onSubmit}
          style={{
            display: "flex",
            gap: 8,
            flexWrap: "wrap",
            alignItems: "flex-end",
          }}
        >
          <FieldWrap label="Description" required>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              style={{ width: 220 }}
            />
          </FieldWrap>
          <FieldWrap label={`Amount (${currency})`} required>
            <Input
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              inputMode="decimal"
              placeholder="0.00"
              style={{ width: 100 }}
            />
          </FieldWrap>
          <FieldWrap label="Who paid?" required>
            <Select
              value={whoPaid}
              onChange={(e) => setWhoPaid(e.target.value as typeof whoPaid)}
              style={{ width: 210 }}
            >
              <option value="" disabled>
                Choose…
              </option>
              <option value="me">I paid, pay me back</option>
              <option value="business">The business paid</option>
            </Select>
          </FieldWrap>
          <FieldWrap label="Receipt photo">
            <Input
              key={photoKey}
              type="file"
              accept="image/*"
              capture="environment"
              onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
              style={{ width: 220 }}
            />
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
                <span>
                  {formatMoney(c.amount_cents, { currency: c.currency })}
                </span>
                <span className="field-label">
                  {c.reimburse === false ? "business paid" : "pay back"}
                </span>
                {c.receipt_sha ? (
                  <Button
                    variant="ghost"
                    onClick={() =>
                      openClaimReceipt(c.id).catch((err) =>
                        setError(
                          err instanceof Error
                            ? err.message
                            : "Could not open the receipt",
                        ),
                      )
                    }
                  >
                    Receipt
                  </Button>
                ) : null}
                <Badge tone={statusTone(c.status)}>{c.status}</Badge>
                {c.status === "submitted" ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      withdrawExpenseClaim(c.id)
                        .then((w) =>
                          setClaims((cur) =>
                            (cur ?? []).map((x) => (x.id === w.id ? w : x)),
                          ),
                        )
                        .catch((err) =>
                          setError(
                            err instanceof ApiError
                              ? err.message
                              : "Could not withdraw the claim",
                          ),
                        )
                    }
                  >
                    Withdraw
                  </Button>
                ) : null}
              </span>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
