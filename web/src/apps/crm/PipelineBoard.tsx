import { fullDate } from "../../ui/resource/fieldFormat";
import { useState, type DragEvent, type FormEvent } from "react";
import { formatMoney } from "../../lib/orgSettings";
import type { RecordRow } from "../../lib/types";
import { PriorityFlag } from "../../ui/PriorityFlag";

/** The open stages, in order, with how likely a deal there is to close:
 * the weights a forecast uses (the Pipedrive/HubSpot default ladder). */
export const OPEN_STAGES: { id: string; label: string; weight: number }[] = [
  { id: "new", label: "New", weight: 0.1 },
  { id: "qualified", label: "Qualified", weight: 0.4 },
  { id: "proposition", label: "Proposal", weight: 0.7 },
];

/** A deal untouched this long is "rotting": it needs a next step. */
const ROT_DAYS = 14;

const value = (o: RecordRow) => Number(o.value_cents) || 0;
const days = (iso: unknown) => (iso ? Math.floor((Date.now() - new Date(String(iso)).getTime()) / 86_400_000) : 0);

/** The sales pipeline board (plan 12.7): a column per open stage with
 * its count, total and weighted value; cards with value, priority, the
 * next step (red when overdue) and how long since anyone touched it;
 * drag between columns or use "Move to" (keyboard and phones); Won/Lost
 * on the card; a quick add at the top of each column. */
export function PipelineBoard({
  deals,
  onOpen,
  onMove,
  onAdd,
}: {
  deals: RecordRow[];
  onOpen: (deal: RecordRow) => void;
  onMove: (deal: RecordRow, stage: string, lostReason?: string) => void;
  onAdd: (stage: string, company: string, valueCents: number) => Promise<void>;
}) {
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null);

  function drop(e: DragEvent, stage: string) {
    e.preventDefault();
    setDragOver(null);
    const deal = deals.find((d) => String(d.id) === e.dataTransfer.getData("text/plain"));
    if (deal && deal.stage !== stage) onMove(deal, stage);
  }
  function lose(deal: RecordRow) {
    const reason = window.prompt(`Why was ${deal.company || deal.contact_name} lost?`, "");
    if (reason !== null) onMove(deal, "lost", reason.trim());
  }

  return (
    <div className="pipeline" role="list" aria-label="Pipeline">
      {OPEN_STAGES.map((s) => {
        const col = deals.filter((d) => d.stage === s.id);
        const total = col.reduce((sum, d) => sum + value(d), 0);
        return (
          <section
            key={s.id}
            role="listitem"
            aria-label={`${s.label}: ${col.length} deals`}
            className={`pipeline-col${dragOver === s.id ? " over" : ""}`}
            onDragOver={(e) => (e.preventDefault(), setDragOver(s.id))}
            onDragLeave={() => setDragOver(null)}
            onDrop={(e) => drop(e, s.id)}
          >
            <header className="pipeline-head">
              <div className="pipeline-title">
                <strong>{s.label}</strong> <span className="pipeline-count">{col.length}</span>
              </div>
              <div className="pipeline-sums">
                {formatMoney(total, { whole: true })}
                <span title={`Weighted at ${Math.round(s.weight * 100)}%: what this stage is likely to bring`}>
                  {" · "}
                  {formatMoney(Math.round(total * s.weight), { whole: true })} likely
                </span>
              </div>
            </header>
            {adding === s.id ? (
              <QuickAdd
                onCancel={() => setAdding(null)}
                onSave={async (company, cents) => {
                  await onAdd(s.id, company, cents);
                  setAdding(null);
                }}
              />
            ) : (
              <button type="button" className="pipeline-add" onClick={() => setAdding(s.id)}>
                + Add deal
              </button>
            )}
            <ul className="pipeline-cards">
              {col.map((d) => {
                const idle = days(d.updated_at);
                const overdue = d.next_step_at && new Date(String(d.next_step_at)).getTime() < Date.now();
                return (
                  <li
                    key={String(d.id)}
                    className={`pipeline-card${idle >= ROT_DAYS ? " rotting" : ""}`}
                    draggable
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", String(d.id))}
                  >
                    <button type="button" className="pipeline-card-main" onClick={() => onOpen(d)}>
                      <span className="pipeline-card-name">{String(d.company || d.contact_name)}</span>
                      {d.company && d.contact_name ? <span className="field-label">{String(d.contact_name)}</span> : null}
                      <span className="pipeline-card-value">{formatMoney(value(d), { whole: true })}</span>
                    </button>
                    <div className="pipeline-card-meta">
                      {d.priority ? <PriorityFlag value={String(d.priority)} /> : null}
                      {d.next_step_at ? (
                        <span className={overdue ? "pipeline-overdue" : "field-label"}>
                          {overdue ? "Overdue: " : "Next: "}
                          {fullDate(String(d.next_step_at), false)}
                        </span>
                      ) : (
                        <span className="pipeline-overdue">No next step</span>
                      )}
                      <span className="field-label" title="Days since anyone touched it">
                        {idle}d
                      </span>
                    </div>
                    <div className="pipeline-card-actions">
                      <label className="sr-only" htmlFor={`move-${d.id}`}>
                        Move to
                      </label>
                      <select
                        id={`move-${d.id}`}
                        value={String(d.stage)}
                        onChange={(e) => (e.target.value === "lost" ? lose(d) : onMove(d, e.target.value))}
                      >
                        {OPEN_STAGES.map((o) => (
                          <option key={o.id} value={o.id}>
                            {o.label}
                          </option>
                        ))}
                        <option value="won">Won</option>
                        <option value="lost">Lost…</option>
                      </select>
                      <button type="button" className="pipeline-won" onClick={() => onMove(d, "won")}>
                        Won
                      </button>
                      <button type="button" className="pipeline-lost" onClick={() => lose(d)}>
                        Lost
                      </button>
                    </div>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function QuickAdd({ onSave, onCancel }: { onSave: (company: string, cents: number) => Promise<void>; onCancel: () => void }) {
  const [company, setCompany] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!company.trim()) return;
    setBusy(true);
    try {
      await onSave(company.trim(), Math.round((Number.parseFloat(amount) || 0) * 100));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="pipeline-quick" onSubmit={submit}>
      <input aria-label="Company or contact" placeholder="Company or contact" value={company} autoFocus onChange={(e) => setCompany(e.target.value)} />
      <input aria-label="Value" inputMode="decimal" placeholder="Value" value={amount} onChange={(e) => setAmount(e.target.value)} />
      <div style={{ display: "flex", gap: 6 }}>
        <button type="submit" className="btn btn-primary btn-sm" disabled={busy || !company.trim()}>
          Add
        </button>
        <button type="button" className="btn btn-secondary btn-sm" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
