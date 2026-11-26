import { useCallback, useEffect, useState, type FormEvent } from "react";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatMoney, useOrgSettings } from "../lib/orgSettings";
import {
  askFirst,
  fetchMySpendRequests,
  fetchOpenTrips,
  fetchRequestsWaitingForMe,
  payTripAdvance,
  settleRequest,
  withdrawSpendRequest,
  CATEGORIES,
  type SpendRequest,
} from "../lib/minions";
import { ClaimDecision } from "../apps/minions/ClaimActions";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";
import { PickList } from "../ui/PickList";

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);
const cents = (v: string) => Math.round((Number.parseFloat(v || "0") || 0) * 100);
const SAYS: Record<SpendRequest["status"], string> = {
  submitted: "Waiting for a decision",
  approved: "Approved: claim against it when you spend",
  rejected: "Turned down",
  withdrawn: "You took it back",
  closed: "Done",
};

/** What a request is, in a line: "Trip to Nakuru, 1-2 Dec" or its description. */
export function requestTitle(r: SpendRequest): string {
  if (r.kind !== "trip") return r.description;
  const day = (d: string | null) => (d ? new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "");
  return `Trip to ${r.destination}, ${day(r.starts_on)}${r.ends_on && r.ends_on !== r.starts_on ? ` to ${day(r.ends_on)}` : ""}`;
}

/** Claims > Ask first: a spend over your amount, or any trip, is asked
 * for before the money goes out; the claim then goes against it. */
export function AskFirst() {
  const { currency } = useOrgSettings();
  const [mine, setMine] = useState<SpendRequest[] | null>(null);
  const [asking, setAsking] = useState<"" | "spend" | "trip">("");
  const [description, setDescription] = useState("");
  const [amount, setAmount] = useState("");
  const [category, setCategory] = useState("other");
  const [destination, setDestination] = useState("");
  const [startsOn, setStartsOn] = useState("");
  const [endsOn, setEndsOn] = useState("");
  const [advance, setAdvance] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchMySpendRequests()
      .then(setMine)
      .catch(() => setMine([]));
  }, []);
  useEffect(load, [load]);

  async function send(e: FormEvent) {
    e.preventDefault();
    if (!description.trim()) return setProblem(asking === "trip" ? "Say what the trip is for" : "Say what you need to buy");
    if (cents(amount) <= 0) return setProblem("About how much will it cost?");
    if (asking === "trip" && (!destination.trim() || !startsOn || !endsOn)) return setProblem("Say where you're going and when");
    setBusy(true);
    setProblem(null);
    try {
      await askFirst({
        kind: asking || "spend",
        description: description.trim(),
        amount_cents: cents(amount),
        category,
        ...(asking === "trip"
          ? { destination: destination.trim(), starts_on: startsOn, ends_on: endsOn, advance_cents: cents(advance) }
          : {}),
      });
      setAsking("");
      setDescription("");
      setAmount("");
      setDestination("");
      setStartsOn("");
      setEndsOn("");
      setAdvance("");
      load();
    } catch (err) {
      setProblem(errorText(err, "Could not send the request"));
    } finally {
      setBusy(false);
    }
  }

  async function takeBack(r: SpendRequest) {
    try {
      await withdrawSpendRequest(r.id);
      load();
    } catch (err) {
      setProblem(errorText(err, "Could not take it back"));
    }
  }

  if (mine === null) return null;
  const shown = mine.filter((r) => r.status !== "withdrawn").slice(0, 10);
  return (
    <section aria-label="Ask first">
      <div className="minions-head">
        <h2 className="minions-group">Ask first</h2>
        {!asking ? (
          <div className="minions-actions">
            <Button size="sm" onClick={() => setAsking("spend")}>
              Ask to spend
            </Button>
            <Button size="sm" onClick={() => setAsking("trip")}>
              Plan a trip
            </Button>
          </div>
        ) : null}
      </div>
      {asking ? (
        <form className="minions-newclaim" onSubmit={send} aria-label={asking === "trip" ? "Plan a trip" : "Ask to spend"}>
          <FieldWrap label={asking === "trip" ? "What the trip is for" : "What you need to buy"} required>
            <Input
              value={description}
              maxLength={300}
              placeholder={asking === "trip" ? "e.g. Visit the Nakuru supplier" : "e.g. Paint for the shopfront"}
              onChange={(e) => setDescription(e.target.value)}
            />
          </FieldWrap>
          {asking === "trip" ? (
            <>
              <FieldWrap label="Where to" required>
                <Input value={destination} maxLength={120} onChange={(e) => setDestination(e.target.value)} />
              </FieldWrap>
              <FieldWrap label="From" required>
                <Input type="date" value={startsOn} onChange={(e) => setStartsOn(e.target.value)} />
              </FieldWrap>
              <FieldWrap label="To" required>
                <Input type="date" value={endsOn} min={startsOn || undefined} onChange={(e) => setEndsOn(e.target.value)} />
              </FieldWrap>
            </>
          ) : null}
          <FieldWrap label={`About how much (${currency})`} required>
            <Input value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
          </FieldWrap>
          {asking === "trip" ? (
            <FieldWrap label={`Cash up front (${currency}, optional)`}>
              <Input value={advance} inputMode="decimal" placeholder="0" onChange={(e) => setAdvance(e.target.value)} />
            </FieldWrap>
          ) : (
            <FieldWrap label="Kind of cost">
              <PickList
                aria-label="Kind of cost"
                value={category}
                onChange={setCategory}
                options={CATEGORIES.map(([value, label]) => ({ value, label }))}
              />
            </FieldWrap>
          )}
          {problem ? (
            <p className="minions-problem" role="alert">
              {problem}
            </p>
          ) : null}
          <div className="minions-actions">
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Sending…" : "Send request"}
            </Button>
            <Button variant="ghost" onClick={() => setAsking("")}>
              Cancel
            </Button>
          </div>
        </form>
      ) : null}
      {!asking && problem ? (
        <p className="minions-problem" role="alert">
          {problem}
        </p>
      ) : null}
      {shown.length ? (
        <ul className="minions-rows">
          {shown.map((r) => (
            <li key={r.id} className="minions-row">
              <div className="minions-row-main">
                <span className="minions-row-title">
                  {formatMoney(r.amount_cents, { currency: r.currency })} for {requestTitle(r)}
                </span>
                <span className="field-label">
                  {SAYS[r.status]}
                  {r.status === "submitted" && r.waiting_on_name ? ` (${r.waiting_on_name})` : ""}
                  {r.status === "rejected" && r.decision_note ? `: ${r.decision_note}` : ""}
                  {r.advance_cents ? `. Cash up front ${formatMoney(r.advance_cents, { currency: r.currency })}${r.advance_paid_at ? ", paid" : ""}` : ""}
                </span>
              </div>
              {r.status === "submitted" ? (
                <Button size="sm" variant="ghost" onClick={() => takeBack(r)}>
                  Take back
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : !asking ? (
        <p className="field-label">Big spends and trips are asked for first. An emergency? Spend, then claim and say why.</p>
      ) : null}
    </section>
  );
}

/** Team: requests and trips waiting for my decision. */
export function WaitingRequests() {
  const [list, setList] = useState<SpendRequest[]>([]);
  const load = () => {
    fetchRequestsWaitingForMe()
      .then(setList)
      .catch(() => setList([]));
  };
  useEffect(load, []);
  if (!list.length) return null;
  return (
    <section aria-label="Asked first, waiting for you">
      <h2 className="minions-group">Asked first, waiting for you</h2>
      <ul className="minions-cardlist">
        {list.map((r) => (
          <li key={r.id} className="minions-parcel">
            <p className="minions-decide-amount">{formatMoney(r.amount_cents, { currency: r.currency })}</p>
            <p className="minions-row-title">{requestTitle(r)}</p>
            <p className="field-label">
              {r.kind === "trip" ? r.description : CATEGORIES.find(([v]) => v === r.category)?.[1]}
              {r.advance_cents ? `. Wants ${formatMoney(r.advance_cents, { currency: r.currency })} up front` : ""}
            </p>
            <ClaimDecision claim={r} onDone={load} base="/api/minions/spend_requests" />
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Team (owners and admins, who pay people): approved trips, to pay the
 * cash up front and to settle once the trip's claims are decided. */
export function OpenTrips() {
  const { session } = useAuth();
  const pays = session?.role === "owner" || session?.role === "admin";
  const [list, setList] = useState<SpendRequest[]>([]);
  const load = useCallback(() => {
    fetchOpenTrips()
      .then(setList)
      .catch(() => setList([]));
  }, []);
  useEffect(() => {
    if (pays) load();
  }, [pays, load]);
  if (!pays || !list.length) return null;
  return (
    <section aria-label="Trips">
      <h2 className="minions-group">Trips</h2>
      <ul className="minions-cardlist">
        {list.map((r) => (
          <TripCard key={r.id} trip={r} onDone={load} />
        ))}
      </ul>
    </section>
  );
}

function TripCard({ trip: r, onDone }: { trip: SpendRequest; onDone: () => void }) {
  const owesAdvance = r.advance_cents > 0 && !r.advance_paid_at;
  const [method, setMethod] = useState(owesAdvance ? "mpesa" : "cash");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const needsRef = method === "mpesa" || method === "bank";

  async function go(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onDone();
    } catch (err) {
      setError(errorText(err, "Could not save that"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="minions-parcel">
      <p className="minions-row-title">{requestTitle(r)}</p>
      <p className="field-label">
        {formatMoney(r.amount_cents, { currency: r.currency })} planned
        {r.advance_cents ? `, ${formatMoney(r.advance_cents, { currency: r.currency })} up front${r.advance_paid_at ? " (paid)" : ""}` : ""}
      </p>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <div className="form-grid">
        <FieldWrap label={owesAdvance ? "Pay the cash up front by" : r.advance_paid_at ? "What's left comes back, or extra is paid, by" : "Close the trip"}>
          {owesAdvance || r.advance_paid_at ? (
            <Select value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="mpesa">M-Pesa</option>
              <option value="bank">Bank transfer</option>
              <option value="cash">Cash</option>
              {!owesAdvance ? <option value="payroll">Off their next pay</option> : null}
            </Select>
          ) : (
            <span className="field-label">No cash up front; its claims are paid the usual way.</span>
          )}
        </FieldWrap>
        {(owesAdvance || r.advance_paid_at) && needsRef ? (
          <FieldWrap label={method === "mpesa" ? "M-Pesa code" : "Bank reference"}>
            <Input value={reference} maxLength={60} onChange={(e) => setReference(e.target.value)} />
          </FieldWrap>
        ) : null}
        <div className="minions-actions">
          {owesAdvance ? (
            <Button variant="primary" disabled={busy || (needsRef && !reference.trim())} onClick={() => go(() => payTripAdvance(r.id, method, reference.trim()))}>
              Pay the advance
            </Button>
          ) : (
            <Button variant="primary" disabled={busy} onClick={() => go(() => settleRequest(r.id, method, reference.trim()))}>
              {r.advance_paid_at ? "Settle the trip" : "Close the trip"}
            </Button>
          )}
        </div>
      </div>
    </li>
  );
}
