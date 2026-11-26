import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { formatMoney, useOrgSettings } from "../lib/orgSettings";
import { listLocations, type Location } from "../lib/people";
import {
  confirmPettySlip,
  countPettyCash,
  createPettyCash,
  fetchPettyCash,
  fetchPettySlips,
  topUpPettyCash,
  type ExpenseClaim,
  type PettyFloat,
} from "../lib/minions";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";

const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);
const cents = (v: string) => Math.round((Number.parseFloat(v || "0") || 0) * 100);
const MOVE: Record<PettyFloat["moves"][number]["kind"], string> = { top_up: "Topped up", slip: "Paid out", count: "Counted" };

/** Claims > Petty cash, for whoever holds a float and those who pay
 * people: what's in it, slips to confirm, counting it, topping it up
 * (never by the holder), and setting one up for a location. */
export function PettyCash() {
  const { session } = useAuth();
  const pays = session?.role === "owner" || session?.role === "admin";
  const [floats, setFloats] = useState<PettyFloat[] | null>(null);
  const [slips, setSlips] = useState<ExpenseClaim[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchPettyCash()
      .then(setFloats)
      .catch(() => setFloats([]));
    fetchPettySlips().then(setSlips);
  }, []);
  useEffect(load, [load]);

  if (floats === null) return null;
  const mine = floats.filter((f) => f.balance_cents !== null); // mine, or all for those who pay
  if (!mine.length && !pays) return null;
  return (
    <section aria-label="Petty cash">
      <h2 className="minions-group">Petty cash</h2>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <ul className="minions-cardlist">
        {mine.map((f) => (
          <FloatCard
            key={f.id}
            float={f}
            slips={slips.filter((c) => c.float_id === f.id)}
            canTopUp={pays && !f.held_by_me}
            pays={pays}
            onDone={load}
            onError={setError}
          />
        ))}
      </ul>
      {pays ? <NewFloat taken={floats.map((f) => f.location_id)} onDone={load} /> : null}
    </section>
  );
}

function FloatCard({
  float: f,
  slips,
  canTopUp,
  pays,
  onDone,
  onError,
}: {
  float: PettyFloat;
  slips: ExpenseClaim[];
  canTopUp: boolean;
  pays: boolean;
  onDone: () => void;
  onError: (m: string | null) => void;
}) {
  const [counting, setCounting] = useState(false);
  const [counted, setCounted] = useState("");
  const [note, setNote] = useState("");
  const [method, setMethod] = useState("mpesa");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  // Handing over (owners and admins): to whom, counted together first.
  const [handing, setHanding] = useState(false);
  const [people, setPeople] = useState<{ user_id: string; name: string }[]>([]);
  const [nextHolder, setNextHolder] = useState("");
  const money = (c: number) => formatMoney(c, { currency: f.currency });
  const balance = f.balance_cents ?? 0;
  const pending = f.pending_cents ?? 0;
  const short = f.float_cents - balance;

  async function act(fn: () => Promise<unknown>, fallback: string) {
    setBusy(true);
    onError(null);
    try {
      await fn();
      setCounting(false);
      setHanding(false);
      setNextHolder("");
      setCounted("");
      setNote("");
      setReference("");
      onDone();
    } catch (err) {
      onError(errorText(err, fallback));
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="minions-parcel">
      <p className="minions-row-title">{f.name}</p>
      <p className="minions-decide-amount">{money(balance - pending)}</p>
      <p className="field-label">
        Should be in the box, of a {money(f.float_cents)} float{pending ? `; ${money(pending)} in slips not yet confirmed` : ""}. Held by{" "}
        {f.holder_name}.
      </p>

      {slips.length ? (
        <ul className="minions-rows">
          {slips.map((c) => (
            <li key={c.id} className="minions-row">
              <div className="minions-row-main">
                <span className="minions-row-title">
                  {money(c.amount_cents)} for {c.description}
                </span>
                <span className="field-label">Approved; did it come out of the box?</span>
              </div>
              <Button size="sm" variant="primary" disabled={busy} onClick={() => act(() => confirmPettySlip(c.id), "Could not confirm it")}>
                Confirm
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      {counting ? (
        <div className="form-grid">
          <FieldWrap label={`Cash counted (${f.currency})`} required>
            <Input autoFocus value={counted} inputMode="decimal" onChange={(e) => setCounted(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Note (needed if it's short)">
            <Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
          </FieldWrap>
          <div className="minions-actions">
            <Button
              variant="primary"
              disabled={busy || !counted}
              onClick={() => act(() => countPettyCash(f.id, cents(counted), note.trim()), "Could not save the count")}
            >
              Save count
            </Button>
            <Button variant="ghost" onClick={() => setCounting(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : handing ? (
        <div className="form-grid">
          <FieldWrap label="Hand it to" required>
            <Select value={nextHolder} onChange={(e) => setNextHolder(e.target.value)}>
              <option value="">Choose…</option>
              {people
                .filter((p) => p.user_id !== f.holder_user_id)
                .map((p) => (
                  <option key={p.user_id} value={p.user_id}>
                    {p.name}
                  </option>
                ))}
            </Select>
          </FieldWrap>
          <FieldWrap label={`Counted together with ${f.holder_name} (${f.currency})`} required>
            <Input value={counted} inputMode="decimal" onChange={(e) => setCounted(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Note (needed if it's short)">
            <Input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
          </FieldWrap>
          <div className="minions-actions">
            <Button
              variant="primary"
              disabled={busy || !nextHolder || !counted}
              onClick={() =>
                act(
                  () => api.patch(`/api/minions/petty_cash/${f.id}`, { holder_user_id: nextHolder, counted_cents: cents(counted), note: note.trim() }),
                  "Could not hand it over",
                )
              }
            >
              Hand over
            </Button>
            <Button variant="ghost" onClick={() => setHanding(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div className="minions-actions">
          <Button size="sm" onClick={() => setCounting(true)}>
            Count it
          </Button>
          {pays ? (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setHanding(true);
                api
                  .get<{ user_id: string; name: string; status: string }[]>("/api/minions/employees")
                  .then((ps) => setPeople(ps.filter((p) => p.user_id && p.status === "active")))
                  .catch(() => {});
              }}
            >
              Hand over
            </Button>
          ) : null}
        </div>
      )}

      {canTopUp && short > 0 ? (
        <div className="form-grid">
          <FieldWrap label={`Top up ${money(short)} from`}>
            <Select value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="mpesa">M-Pesa</option>
              <option value="bank">Bank</option>
              <option value="cash">Cash</option>
            </Select>
          </FieldWrap>
          {method !== "cash" ? (
            <FieldWrap label={method === "mpesa" ? "M-Pesa code" : "Bank reference"} required>
              <Input value={reference} maxLength={60} onChange={(e) => setReference(e.target.value)} />
            </FieldWrap>
          ) : null}
          <div className="minions-actions">
            <Button
              variant="primary"
              disabled={busy || (method !== "cash" && !reference.trim())}
              onClick={() => act(() => topUpPettyCash(f.id, method, reference.trim()), "Could not top it up")}
            >
              Top up
            </Button>
          </div>
        </div>
      ) : null}

      {f.moves.length ? (
        <details>
          <summary className="field-label">Recent</summary>
          <ul className="minions-rows">
            {f.moves.map((m) => (
              <li key={m.id} className="minions-row">
                <span className="field-label">
                  {new Date(m.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })} {MOVE[m.kind]}
                  {m.kind === "count" ? (m.amount_cents ? (m.amount_cents > 0 ? `, ${money(m.amount_cents)} over` : `, ${money(-m.amount_cents)} short`) : ", agreed") : ` ${money(Math.abs(m.amount_cents))}`}
                  {m.by_name ? ` by ${m.by_name}` : ""}
                  {m.note ? `: ${m.note}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </li>
  );
}

/** Owners and admins: a float for a location, held by one person. */
function NewFloat({ taken, onDone }: { taken: string[]; onDone: () => void }) {
  const { currency } = useOrgSettings();
  const [open, setOpen] = useState(false);
  const [places, setPlaces] = useState<Location[]>([]);
  const [people, setPeople] = useState<{ user_id: string; name: string; status: string }[]>([]);
  const [location, setLocation] = useState("");
  const [holder, setHolder] = useState("");
  const [size, setSize] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    listLocations().then(setPlaces).catch(() => {});
    api
      .get<{ user_id: string; name: string; status: string }[]>("/api/minions/employees")
      .then((ps) => setPeople(ps.filter((p) => p.user_id && p.status === "active")))
      .catch(() => {});
  }, [open]);

  if (!open)
    return (
      <Button size="sm" onClick={() => setOpen(true)}>
        Set up petty cash
      </Button>
    );
  const free = places.filter((p) => !taken.includes(p.id));

  async function save() {
    if (!holder) return setProblem("Choose who holds it");
    setBusy(true);
    setProblem(null);
    try {
      const place = places.find((p) => p.id === location);
      await createPettyCash({
        name: `${place?.name ?? "Main"} petty cash`,
        location_id: location,
        holder_user_id: holder,
        ...(cents(size) > 0 ? { float_cents: cents(size) } : {}),
      });
      setOpen(false);
      onDone();
    } catch (err) {
      setProblem(errorText(err, "Could not set it up"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="minions-newclaim" role="group" aria-label="Set up petty cash">
      <FieldWrap label="Location">
        <Select value={location} onChange={(e) => setLocation(e.target.value)}>
          <option value="">The whole business</option>
          {free.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
      </FieldWrap>
      <FieldWrap label="Who holds it" required>
        <Select value={holder} onChange={(e) => setHolder(e.target.value)}>
          <option value="">Choose…</option>
          {people.map((p) => (
            <option key={p.user_id} value={p.user_id}>
              {p.name}
            </option>
          ))}
        </Select>
      </FieldWrap>
      <FieldWrap label={`Float (${currency}); empty: your spending policy's`}>
        <Input value={size} inputMode="decimal" onChange={(e) => setSize(e.target.value)} />
      </FieldWrap>
      <p className="field-label">It starts empty: someone other than the holder tops it up.</p>
      {problem ? (
        <p className="minions-problem" role="alert">
          {problem}
        </p>
      ) : null}
      <div className="minions-actions">
        <Button variant="primary" disabled={busy} onClick={save}>
          Set it up
        </Button>
        <Button variant="ghost" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
