import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiError } from "../lib/api";
import { formatMoney, useOrgSettings } from "../lib/orgSettings";
import { Button } from "../ui/Button";
import { FieldWrap, Input, Select } from "../ui/Field";

interface Advance {
  id: string;
  amount_cents: number;
  currency: string;
  months: number;
  status: "submitted" | "approved" | "rejected" | "paid" | "recovered" | "withdrawn";
  description: string;
  waiting_on_name: string;
  decided_by_name: string;
  decision_note: string;
  recovered_cents: number;
}

const SAYS: Record<Advance["status"], string> = {
  submitted: "Waiting for a decision",
  approved: "Approved, not paid out yet",
  rejected: "Turned down",
  paid: "Paid to you; coming off your pay",
  recovered: "Paid back",
  withdrawn: "You took it back",
};
const errorText = (err: unknown, fallback: string) => (err instanceof ApiError ? err.message : fallback);

/** Pay > Advances: ask for part of next pay early (at most half of one
 * pay, paid back over 1-3 pay runs), and where mine are. */
export function Advances() {
  const { currency } = useOrgSettings();
  const [mine, setMine] = useState<Advance[] | null>(null);
  const [asking, setAsking] = useState(false);
  const [amount, setAmount] = useState("");
  const [months, setMonths] = useState("1");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<Advance[]>("/api/minions/salary_advances?mine=true")
      .then(setMine)
      .catch(() => setMine([]));
  }, []);
  useEffect(load, [load]);

  const open = (mine ?? []).find((a) => ["submitted", "approved", "paid"].includes(a.status));

  async function ask(e: FormEvent) {
    e.preventDefault();
    const cents = Math.round((Number.parseFloat(amount || "0") || 0) * 100);
    if (cents <= 0) return setProblem("How much do you need?");
    setBusy(true);
    setProblem(null);
    try {
      await api.post("/api/minions/salary_advances", { amount_cents: cents, months: Number(months), description: why.trim() });
      setAsking(false);
      setAmount("");
      setWhy("");
      load();
    } catch (err) {
      setProblem(errorText(err, "Could not send the request"));
    } finally {
      setBusy(false);
    }
  }

  async function takeBack(a: Advance) {
    try {
      await api.post(`/api/minions/salary_advances/${a.id}/withdraw`);
      load();
    } catch (err) {
      setProblem(errorText(err, "Could not take it back"));
    }
  }

  if (mine === null) return null;
  return (
    <section aria-label="Salary advances">
      <div className="minions-head">
        <h2 className="minions-group">Advances</h2>
        {!open && !asking ? (
          <Button size="sm" onClick={() => setAsking(true)}>
            Ask for an advance
          </Button>
        ) : null}
      </div>
      {asking ? (
        <form className="minions-newclaim" onSubmit={ask} aria-label="Ask for an advance">
          <FieldWrap label={`How much (${currency}), at most half of one pay`} required>
            <Input value={amount} inputMode="decimal" onChange={(e) => setAmount(e.target.value)} />
          </FieldWrap>
          <FieldWrap label="Pay it back over">
            <Select value={months} onChange={(e) => setMonths(e.target.value)}>
              <option value="1">My next pay</option>
              <option value="2">My next 2 pays</option>
              <option value="3">My next 3 pays</option>
            </Select>
          </FieldWrap>
          <FieldWrap label="What for (optional)">
            <Input value={why} maxLength={300} placeholder="e.g. School fees" onChange={(e) => setWhy(e.target.value)} />
          </FieldWrap>
          {problem ? (
            <p className="minions-problem" role="alert">
              {problem}
            </p>
          ) : null}
          <div className="minions-actions">
            <Button type="submit" variant="primary" disabled={busy}>
              {busy ? "Sending…" : "Send request"}
            </Button>
            <Button variant="ghost" onClick={() => setAsking(false)}>
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
      {mine.length ? (
        <ul className="minions-rows">
          {mine.map((a) => (
            <li key={a.id} className="minions-row">
              <div className="minions-row-main">
                <span className="minions-row-title">{formatMoney(a.amount_cents, { currency: a.currency })}</span>
                <span className="field-label">
                  {SAYS[a.status]}
                  {a.status === "submitted" && a.waiting_on_name ? ` (${a.waiting_on_name})` : ""}
                  {a.status === "rejected" && a.decision_note ? `: ${a.decision_note}` : ""}
                  {a.status === "paid" ? `, ${formatMoney(a.recovered_cents, { currency: a.currency })} back so far` : ""}
                </span>
              </div>
              {a.status === "submitted" ? (
                <Button size="sm" variant="ghost" onClick={() => takeBack(a)}>
                  Take back
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : !asking ? (
        <p className="field-label">Need part of your pay early? Ask here; it comes off your next pay.</p>
      ) : null}
    </section>
  );
}
