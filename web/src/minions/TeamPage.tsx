import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { formatMoney } from "../lib/orgSettings";
import { openClaimReceipt, type ExpenseClaim } from "../lib/minions";
import { Button } from "../ui/Button";

interface TeamMember {
  id: string;
  name: string;
  email: string;
  department: string;
  status: string;
}

/** Team (team leaders and managers): claims waiting for my decision, and
 * who's on my team. The server decides what's mine to see and approve
 * (plan 12.2), including my approval limit; refusals say who can. */
export function TeamPage() {
  const [claims, setClaims] = useState<ExpenseClaim[] | null>(null);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  function load() {
    api
      .get<ExpenseClaim[]>("/api/minions/expense_claims")
      .then((rows) => setClaims(rows.filter((c) => c.status === "submitted")))
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load claims"));
    api
      .get<TeamMember[]>("/api/minions/employees")
      .then(setTeam)
      .catch(() => {});
  }
  useEffect(load, []);
  const nameOf = (employeeId: string) => team.find((t) => t.id === employeeId)?.name ?? "Someone";

  async function decide(claim: ExpenseClaim, status: "approved" | "rejected") {
    setBusy(claim.id);
    setError(null);
    try {
      await api.patch(`/api/minions/expense_claims/${claim.id}/status`, { status });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not save");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="page minions-page">
      <h1 className="page-title">Team</h1>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}
      <section className="card card-padded">
        <h2 className="minions-h2">Waiting for you</h2>
        {claims === null ? (
          <div className="spinner">Loading…</div>
        ) : claims.length === 0 ? (
          <p className="field-label">Nothing to decide.</p>
        ) : (
          <ul className="minions-cards">
            {claims.map((c) => (
              <li key={c.id} className="minions-claim">
                <div>
                  <div style={{ fontWeight: 600 }}>
                    {nameOf(c.employee_id)} · {formatMoney(c.amount_cents, { currency: c.currency })}
                  </div>
                  <div className="field-label">
                    {c.description}
                    {c.reimburse === false ? " · business paid" : " · pay back"}
                    {c.receipt_sha ? (
                      <>
                        {" · "}
                        <Button variant="ghost" size="sm" onClick={() => void openClaimReceipt(c.id).catch(() => {})}>
                          Receipt
                        </Button>
                      </>
                    ) : null}
                  </div>
                </div>
                <div className="minions-claim-actions">
                  <Button size="sm" disabled={busy === c.id} onClick={() => decide(c, "rejected")}>
                    Reject
                  </Button>
                  <Button size="sm" variant="primary" disabled={busy === c.id} onClick={() => decide(c, "approved")}>
                    Approve
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="card card-padded">
        <h2 className="minions-h2">My team</h2>
        {team.length === 0 ? (
          <p className="field-label">Nobody reports to you yet. An owner or admin sets that in People.</p>
        ) : (
          <ul className="minions-list">
            {team.map((t) => (
              <li key={t.id}>
                <strong>{t.name}</strong> <span className="field-label">· {t.department || t.email}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
