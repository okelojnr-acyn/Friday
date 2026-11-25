import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { formatMoney } from "../lib/orgSettings";
import { claimReceiptBlob, fetchClaimsWaitingForMe, type ExpenseClaim } from "../lib/minions";
import { ClaimDecision } from "../apps/minions/ClaimActions";

interface TeamMember {
  id: string;
  name: string;
  email: string;
  department: string;
  status: string;
}

/** Team (team leaders and managers): claims waiting for my decision, each
 * with its receipt on the card, and who's on my team. The server decides
 * what's mine (routing up the reporting line, my limit); refusals say who can. */
export function TeamPage() {
  const [claims, setClaims] = useState<ExpenseClaim[] | null>(null);
  const [team, setTeam] = useState<TeamMember[]>([]);
  const [error, setError] = useState<string | null>(null);

  function load() {
    fetchClaimsWaitingForMe()
      .then(setClaims)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the claims"));
    api
      .get<TeamMember[]>("/api/minions/employees")
      .then(setTeam)
      .catch(() => {});
  }
  useEffect(load, []);
  const nameOf = (employeeId: string) => team.find((t) => t.id === employeeId)?.name ?? "Someone";

  return (
    <div className="page minions-page">
      <h1 className="page-title">Team</h1>
      {error ? (
        <div className="error-banner" role="alert">
          {error}
        </div>
      ) : null}

      <section aria-label="Waiting for you">
        <h2 className="minions-group">Waiting for you</h2>
        {claims === null && !error ? <div className="spinner">Loading…</div> : null}
        {claims && claims.length === 0 ? (
          <div className="minions-empty">
            <p className="minions-empty-title">Nothing to decide</p>
            <p className="field-label">When someone you look after sends a claim, it shows up here, and on Telegram if you've linked Guss.</p>
          </div>
        ) : null}
        <ul className="minions-cardlist">
          {(claims ?? []).map((c) => (
            <li key={c.id} className="minions-decide">
              <ReceiptThumb claim={c} />
              <div className="minions-decide-main">
                <p className="minions-decide-amount">{formatMoney(c.amount_cents, { currency: c.currency })}</p>
                <p className="minions-row-title">{c.description}</p>
                <p className="field-label">
                  {nameOf(c.employee_id)}, {c.reimburse === false ? "the business paid" : "wants it paid back"},{" "}
                  {new Date(c.submitted_at).toLocaleDateString(undefined, { day: "numeric", month: "short" })}
                </p>
                <ClaimDecision claim={c} onDone={load} />
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="My team">
        <h2 className="minions-group">My team</h2>
        {team.length === 0 ? (
          <p className="field-label">Nobody reports to you yet. An owner or admin sets that in People.</p>
        ) : (
          <ul className="minions-rows">
            {team.map((t) => (
              <li key={t.id} className="minions-row">
                <div className="minions-row-main">
                  <span className="minions-row-title">{t.name}</span>
                  <span className="field-label">{t.department || t.email}</span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** The receipt right on the card, so deciding needs no extra tap; tap to
 * see it full size. */
function ReceiptThumb({ claim }: { claim: ExpenseClaim }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!claim.receipt_sha) return;
    let made = "";
    claimReceiptBlob(claim.id)
      .then((b) => setUrl((made = URL.createObjectURL(b))))
      .catch(() => {});
    return () => {
      if (made) URL.revokeObjectURL(made);
    };
  }, [claim.id, claim.receipt_sha]);
  if (!claim.receipt_sha) return <div className="minions-thumb empty">No receipt</div>;
  if (!url) return <div className="minions-thumb empty">Loading…</div>;
  return (
    <a className="minions-thumb" href={url} target="_blank" rel="noreferrer" title="Open the receipt full size">
      <img src={url} alt={`Receipt for ${claim.description}`} />
    </a>
  );
}
