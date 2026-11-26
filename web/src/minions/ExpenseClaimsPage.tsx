import { useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../lib/api";
import {
  fetchMyExpenseClaims,
  fetchMyOpenRequests,
  fetchPettyCash,
  type PettyFloat,
  openClaimReceipt,
  resendExpenseClaim,
  submitExpenseClaim,
  uploadClaimReceipt,
  withdrawExpenseClaim,
  CATEGORIES,
  type ExpenseClaim,
  type ForKind,
  type PaidFrom,
  type SpendRequest,
} from "../lib/minions";
import { AskFirst, requestTitle } from "./SpendRequests";
import { PettyCash } from "./PettyCash";
import { api } from "../lib/api";
import { listRecords } from "../lib/resourceApi";
import { PickList, type PickOption } from "../ui/PickList";
import { Button } from "../ui/Button";
import { FieldWrap, Input } from "../ui/Field";
import { formatMoney, useOrgSettings } from "../lib/orgSettings";

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Claims: a new claim starts with the receipt photo (most of them are
 * a receipt in hand), then amount, what for, who paid. Below, each claim
 * shows where it is: sent, approved, paid, or why it was rejected. */
export function ExpenseClaimsPage() {
  const [claims, setClaims] = useState<ExpenseClaim[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMyExpenseClaims()
      .then(setClaims)
      .catch((err) => setError(errorText(err, "Could not load your claims")));
  }, []);

  const replace = (c: ExpenseClaim) => setClaims((cur) => (cur ?? []).map((x) => (x.id === c.id ? c : x)));

  return (
    <div className="page minions-page">
      <h1 className="page-title">Claims</h1>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      <NewClaim onSent={(c) => setClaims((cur) => [c, ...(cur ?? [])])} onError={setError} />
      <AskFirst />
      <PettyCash />

      {claims === null && !error ? <div className="spinner">Loading your claims…</div> : null}
      {claims && claims.length === 0 ? (
        <div className="minions-empty">
          <p className="minions-empty-title">No claims yet</p>
          <p className="field-label">Spent your own money on the business? Take a photo of the receipt above.</p>
        </div>
      ) : null}
      {claims && claims.length ? (
        <section aria-label="My claims">
          <h2 className="minions-group">My claims</h2>
          <ul className="minions-rows">
            {claims.map((c) => (
              <ClaimRow key={c.id} claim={c} onChanged={replace} onError={setError} />
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function NewClaim({ onSent, onError }: { onSent: (c: ExpenseClaim) => void; onError: (m: string | null) => void }) {
  const { currency } = useOrgSettings();
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [photoKey, setPhotoKey] = useState(0); // resets the file input
  const [amount, setAmount] = useState("");
  const [description, setDescription] = useState("");
  // Which money paid it varies person to person (owner, 2026-11-22), so always ask.
  const [whoPaid, setWhoPaid] = useState<"" | PaidFrom>("");
  const [forKind, setForKind] = useState<FormFor>("daily");
  const [forPick, setForPick] = useState<PickOption | null>(null);
  const [category, setCategory] = useState("");
  const [reason, setReason] = useState("");
  const [etims, setEtims] = useState("");
  // Asked first: the approval it was spent under; else, when the server
  // says it needed asking, why it was an emergency.
  const [approvals, setApprovals] = useState<SpendRequest[]>([]);
  const [requestId, setRequestId] = useState("");
  const [emergency, setEmergency] = useState<string | null>(null);
  // Petty cash: which box, when there's more than one.
  const [floats, setFloats] = useState<PettyFloat[]>([]);
  const [floatId, setFloatId] = useState("");
  const [sending, setSending] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    fetchMyOpenRequests()
      .then((rs) => setApprovals(rs.filter((r) => r.kind === "spend")))
      .catch(() => {});
    fetchPettyCash()
      .then(setFloats)
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!photo) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  async function send(e: FormEvent) {
    e.preventDefault();
    const cents = Math.round(Number.parseFloat(amount || "0") * 100);
    if (!Number.isFinite(cents) || cents <= 0) return setProblem("Enter the amount on the receipt");
    if (!description.trim()) return setProblem("Say what you bought");
    if (forKind !== "daily" && !requestId && !forPick) return setProblem(`Choose the ${FOR_NAME[forKind]} it was for`);
    if (!category) return setProblem("Choose what kind of cost it is");
    if (!whoPaid) return setProblem("Say whose money paid");
    if (whoPaid === "petty_cash" && floats.length > 1 && !floatId) return setProblem("Say which petty cash it came out of");
    if (!photo && !reason.trim()) return setProblem("Take a photo of the receipt, or say why there isn't one");
    setProblem(null);
    onError(null);
    setSending(true);
    try {
      let claim = await submitExpenseClaim({
        description: description.trim(),
        amount_cents: cents,
        currency,
        reimburse: whoPaid === "own",
        paid_from: whoPaid,
        for_kind: forKind,
        for_id: forPick?.value ?? "",
        for_label: forPick?.label ?? "",
        category,
        no_receipt_reason: photo ? "" : reason.trim(),
        etims_invoice_no: etims.trim(),
        ...(requestId ? { request_id: requestId } : {}),
        ...(emergency?.trim() ? { emergency_reason: emergency.trim() } : {}),
        ...(whoPaid === "petty_cash" && floatId ? { float_id: floatId } : {}),
      });
      if (photo) {
        try {
          claim = await uploadClaimReceipt(claim.id, photo);
        } catch (err) {
          onError(`Claim sent, but the photo didn't upload: ${err instanceof Error ? err.message : "try again"}`);
        }
      }
      onSent(claim);
      setPhoto(null);
      setPhotoKey((k) => k + 1);
      setAmount("");
      setDescription("");
      setWhoPaid("");
      setForKind("daily");
      setForPick(null);
      setCategory("");
      setReason("");
      setEtims("");
      setRequestId("");
      setEmergency(null);
      setFloatId("");
    } catch (err) {
      const message = errorText(err, "Could not send the claim");
      if (message.includes("asking first") && emergency === null) setEmergency("");
      setProblem(message);
    } finally {
      setSending(false);
    }
  }

  return (
    <form className="minions-newclaim" onSubmit={send} aria-label="New claim">
      <label className={`minions-camera${preview ? " has-photo" : ""}`}>
        {preview ? <img src={preview} alt="Receipt you're attaching" /> : <span>Take a photo of the receipt</span>}
        <input
          key={photoKey}
          type="file"
          accept="image/*"
          capture="environment"
          onChange={(e) => setPhoto(e.target.files?.[0] ?? null)}
        />
      </label>
      {preview ? <span className="field-label">Tap the photo to take it again.</span> : null}
      <FieldWrap label={`Amount (${currency})`} required>
        <Input
          value={amount}
          inputMode="decimal"
          placeholder="0"
          onChange={(e) => setAmount(e.target.value)}
        />
      </FieldWrap>
      {!preview ? (
        <FieldWrap label="No receipt? Say why (small amounts only, a few times a year)">
          <Input value={reason} maxLength={200} placeholder="e.g. Boda boda, no receipt given" onChange={(e) => setReason(e.target.value)} />
        </FieldWrap>
      ) : null}
      <FieldWrap label="What you bought" required>
        <Input
          value={description}
          maxLength={200}
          placeholder="e.g. Taxi to the supplier"
          onChange={(e) => setDescription(e.target.value)}
        />
      </FieldWrap>
      {approvals.length ? (
        <FieldWrap label="Asked first? Pick the approval">
          <PickList
            aria-label="Asked first"
            value={requestId}
            onChange={setRequestId}
            options={[{ value: "", label: "No" }, ...approvals.map((r) => ({ value: r.id, label: requestTitle(r) }))]}
          />
        </FieldWrap>
      ) : null}
      {emergency !== null && !requestId ? (
        <FieldWrap label="An emergency? Say why you couldn't ask first" required>
          <Input value={emergency} maxLength={300} placeholder="e.g. A pipe burst at night" onChange={(e) => setEmergency(e.target.value)} />
        </FieldWrap>
      ) : null}
      {/* An approval already says what it was for. */}
      {requestId ? null : (
        <>
          <fieldset className="minions-choice">
            <legend>What was it for?</legend>
            {(Object.keys(FOR_NAME) as FormFor[]).map((k) => (
              <button key={k} type="button" aria-pressed={forKind === k} onClick={() => (setForKind(k), setForPick(null))}>
                {FOR_LABEL[k]}
              </button>
            ))}
          </fieldset>
          {forKind !== "daily" ? <ForPicker kind={forKind} value={forPick} onChange={setForPick} /> : null}
        </>
      )}
      <FieldWrap label="Kind of cost" required>
        <PickList
          aria-label="Kind of cost"
          placeholder="Transport, fuel, meals…"
          value={category}
          onChange={setCategory}
          options={CATEGORIES.map(([value, label]) => ({ value, label }))}
        />
      </FieldWrap>
      <fieldset className="minions-choice">
        <legend>Whose money paid?</legend>
        <button type="button" aria-pressed={whoPaid === "own"} onClick={() => setWhoPaid("own")}>
          Mine, pay me back
        </button>
        <button type="button" aria-pressed={whoPaid === "petty_cash"} onClick={() => setWhoPaid("petty_cash")}>
          Petty cash or the till
        </button>
        <button type="button" aria-pressed={whoPaid === "business"} onClick={() => setWhoPaid("business")}>
          The business's M-Pesa, card or bank
        </button>
      </fieldset>
      {whoPaid === "petty_cash" && floats.length > 1 ? (
        <FieldWrap label="Which petty cash" required>
          <PickList
            aria-label="Which petty cash"
            value={floatId}
            onChange={setFloatId}
            options={floats.map((f) => ({ value: f.id, label: `${f.name} (${f.holder_name})` }))}
          />
        </FieldWrap>
      ) : null}
      <FieldWrap label="eTIMS invoice number (if the seller gave one)">
        <Input value={etims} maxLength={40} onChange={(e) => setEtims(e.target.value)} />
      </FieldWrap>
      {problem ? (
        <p className="minions-problem" role="alert">
          {problem}
        </p>
      ) : null}
      <Button type="submit" variant="primary" disabled={sending}>
        {sending ? "Sending…" : "Send claim"}
      </Button>
    </form>
  );
}

/** Sent -> Approved -> Paid ("Recorded" when the business paid). */
function steps(c: ExpenseClaim): { labels: string[]; at: number } {
  const last = c.reimburse === false ? "Recorded" : "Paid";
  const at = c.status === "paid" ? 2 : c.status === "approved" ? (c.reimburse === false ? 2 : 1) : 0;
  return { labels: ["Sent", "Approved", last], at };
}

const PAID_BY: Record<string, string> = {
  mpesa: "by M-Pesa",
  bank: "by bank transfer",
  cash: "in cash",
  crypto: "to your wallet",
};

function ClaimRow({
  claim: c,
  onChanged,
  onError,
}: {
  claim: ExpenseClaim;
  onChanged: (c: ExpenseClaim) => void;
  onError: (m: string | null) => void;
}) {
  const [fixing, setFixing] = useState(false);
  const [description, setDescription] = useState(c.description);
  const [amount, setAmount] = useState((c.amount_cents / 100).toFixed(2));
  const [busy, setBusy] = useState(false);
  const closed = c.status === "rejected" || c.status === "withdrawn";
  const { labels, at } = steps(c);

  async function act(fn: () => Promise<ExpenseClaim>, fallback: string) {
    setBusy(true);
    onError(null);
    try {
      onChanged(await fn());
      setFixing(false);
    } catch (err) {
      onError(errorText(err, fallback));
    } finally {
      setBusy(false);
    }
  }

  function resend() {
    const cents = Math.round(Number.parseFloat(amount || "0") * 100);
    if (!description.trim() || !Number.isFinite(cents) || cents <= 0) {
      onError("A description and a positive amount are needed");
      return;
    }
    void act(
      () => resendExpenseClaim(c.id, { description: description.trim(), amount_cents: cents }),
      "Could not send it again",
    );
  }

  return (
    <li className="minions-row minions-claimrow">
      <div className="minions-row-main">
        <span className="minions-row-title">
          {formatMoney(c.amount_cents, { currency: c.currency })} for {c.description}
        </span>
        <span className="field-label">
          {new Date(c.submitted_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })},{" "}
          {c.reimburse === false ? "the business paid" : "to pay you back"}
        </span>

        {closed ? (
          <p className={`minions-claimstate${c.status === "rejected" ? " danger" : ""}`}>
            {c.status === "withdrawn"
              ? "You took it back"
              : `${c.decided_by_name || "Your manager"} rejected it${c.decision_note ? `: ${c.decision_note}` : ""}`}
          </p>
        ) : (
          <ol className="minions-steps" aria-label="Progress">
            {labels.map((s, i) => (
              <li key={s} className={i <= at ? "reached" : undefined} aria-current={i === at ? "step" : undefined}>
                {s}
              </li>
            ))}
          </ol>
        )}
        {c.status === "submitted" && c.waiting_on_name ? (
          <span className="field-label">Waiting for {c.waiting_on_name}</span>
        ) : null}
        {c.status === "paid" && c.paid_method ? (
          <span className="field-label">
            Paid {PAID_BY[c.paid_method] ?? ""}
            {c.paid_reference ? ` (${c.paid_reference})` : ""}
          </span>
        ) : null}

        {fixing ? (
          <div className="minions-fix">
            <FieldWrap label="What for">
              <Input value={description} onChange={(e) => setDescription(e.target.value)} />
            </FieldWrap>
            <FieldWrap label="Amount">
              <Input value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
            </FieldWrap>
            <div className="minions-actions">
              <Button variant="primary" size="sm" disabled={busy} onClick={resend}>
                Send again
              </Button>
              <Button variant="ghost" size="sm" disabled={busy} onClick={() => setFixing(false)}>
                Cancel
              </Button>
            </div>
          </div>
        ) : (
          <div className="minions-actions">
            {c.receipt_sha ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => openClaimReceipt(c.id).catch((err) => onError(errorText(err, "Could not open the receipt")))}
              >
                Receipt
              </Button>
            ) : null}
            {c.status === "rejected" && c.decided_by_name ? (
              <Button size="sm" onClick={() => setFixing(true)}>
                Fix and send again
              </Button>
            ) : null}
            {c.status === "submitted" ? (
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => act(() => withdrawExpenseClaim(c.id), "Could not take the claim back")}
              >
                Take back
              </Button>
            ) : null}
          </div>
        )}
      </div>
    </li>
  );
}

const FOR_NAME: Record<ForKind, string> = {
  daily: "daily running",
  task: "task",
  project: "project",
  vehicle: "vehicle",
  trip: "trip",
  meeting: "meeting",
};
type FormFor = keyof typeof FOR_NAME;
const FOR_LABEL: Record<FormFor, string> = {
  daily: "Daily running",
  task: "A task",
  project: "A project",
  vehicle: "A vehicle",
  trip: "A trip",
  meeting: "A meeting",
};

/** The task (mine), project, vehicle, approved trip (mine) or meeting
 * (mine, the last 60 days) a claim was for, searchable. */
function ForPicker({ kind, value, onChange }: { kind: FormFor; value: PickOption | null; onChange: (o: PickOption | null) => void }) {
  const [options, setOptions] = useState<PickOption[] | null>(null);
  useEffect(() => {
    setOptions(null);
    const since = new Date(Date.now() - 60 * 86_400_000).toISOString();
    const load =
      kind === "trip"
        ? fetchMyOpenRequests().then((rs) => rs.filter((r) => r.kind === "trip").map((r) => ({ value: r.id, label: requestTitle(r) })))
        : kind === "meeting"
        ? api.get<{ id: string; title: string; starts_at: string }[]>(`/api/minions/meetings?mine=true&start=${since}`).then((ms) =>
            ms.map((m) => ({
              value: m.id,
              label: `${m.title}, ${new Date(m.starts_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}`,
            })),
          )
        : kind === "task"
        ? api.get<{ id: string; title: string; status: string }[]>("/api/projects/tasks?mine=true").then((ts) =>
            ts.filter((t) => t.status !== "done").map((t) => ({ value: t.id, label: t.title })),
          )
        : listRecords(kind === "project" ? "projects" : "fleets", kind === "project" ? "project" : "vehicle").then((rows) =>
            rows.map((r) => ({
              value: String(r.id),
              label: [r.name, r.plate_number].filter(Boolean).join(", ") || String(r.id),
            })),
          );
    load.then(setOptions).catch(() => setOptions([]));
  }, [kind]);
  return (
    <FieldWrap label={`Which ${FOR_NAME[kind]}`} required>
      <PickList
        aria-label={`Which ${kind}`}
        placeholder="Search…"
        value={value?.value ?? ""}
        options={options}
        onChange={(v) => onChange(options?.find((o) => o.value === v) ?? null)}
      />
    </FieldWrap>
  );
}
