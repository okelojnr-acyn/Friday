import { WhosIn } from "./WhosIn";
import { CoverCard } from "./CoverCard";
import { WaitingTimeOff } from "./TimeOff";
import { useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import { formatMoney } from "../lib/orgSettings";
import { claimReceiptBlob, fetchClaimsWaitingForMe, type ExpenseClaim } from "../lib/minions";
import { ClaimDecision } from "../apps/minions/ClaimActions";
import { GiveTask } from "./GiveTask";

interface TeamTask {
  id: string;
  status: string;
  assignee_user_id?: string;
  due_at: string | null;
}

interface TeamMember {
  id: string;
  user_id: string;
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
  const [tasks, setTasks] = useState<TeamTask[]>([]);
  const [error, setError] = useState<string | null>(null);

  function load() {
    fetchClaimsWaitingForMe()
      .then(setClaims)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Could not load the claims"));
    api
      .get<TeamMember[]>("/api/minions/employees")
      .then(setTeam)
      .catch(() => {});
    api
      .get<TeamTask[]>("/api/projects/tasks")
      .then(setTasks)
      .catch(() => {});
  }
  useEffect(load, []);
  const nameOf = (employeeId: string) => team.find((t) => t.id === employeeId)?.name ?? "Someone";

  return (
    <div className="page minions-page">
      <h1 className="page-title">Team</h1>
      <WhosIn />
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

      <CoverCard />
      <WaitingAdvances />
      <WaitingTimeOff
        Decision={({ item, onDone }) => <ClaimDecision claim={item} onDone={onDone} base="/api/minions/time_off" />}
      />

      <section aria-label="Give a task">
        <h2 className="minions-group">Give a task</h2>
        <GiveTask
          people={team.filter((t) => t.user_id && t.status !== "terminated").map((t) => ({ user_id: t.user_id, name: t.name }))}
          onGiven={load}
        />
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
                <TaskCounts tasks={tasks.filter((k) => k.assignee_user_id && k.assignee_user_id === t.user_id)} />
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

/** A person's open tasks, and how many are overdue. */
function TaskCounts({ tasks }: { tasks: TeamTask[] }) {
  const open = tasks.filter((t) => t.status !== "done");
  const late = open.filter((t) => t.due_at && new Date(t.due_at).getTime() < Date.now()).length;
  if (!open.length) return <span className="field-label">No open tasks</span>;
  return (
    <span className={`field-label${late ? " minions-flag" : ""}`}>
      {open.length} open{late ? `, ${late} overdue` : ""}
    </span>
  );
}

interface WaitingAdvance {
  id: string;
  employee_id: string;
  amount_cents: number;
  currency: string;
  months: number;
  description: string;
}

/** Advances waiting for my decision (an older Minions has none). */
function WaitingAdvances() {
  const [list, setList] = useState<WaitingAdvance[]>([]);
  const load = () => {
    api
      .get<WaitingAdvance[]>("/api/minions/salary_advances?waiting=true")
      .then(setList)
      .catch(() => setList([]));
  };
  useEffect(load, []);
  if (!list.length) return null;
  return (
    <section aria-label="Advances waiting for you">
      <h2 className="minions-group">Advances waiting for you</h2>
      <ul className="minions-cardlist">
        {list.map((a) => (
          <li key={a.id} className="minions-parcel">
            <p className="minions-decide-amount">{formatMoney(a.amount_cents, { currency: a.currency })}</p>
            <p className="field-label">
              Paid back over {a.months} {a.months === 1 ? "pay" : "pays"}
              {a.description ? `, for ${a.description}` : ""}
            </p>
            <ClaimDecision claim={a} onDone={load} base="/api/minions/salary_advances" />
          </li>
        ))}
      </ul>
    </section>
  );
}
