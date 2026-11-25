import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { formatMoney } from "../lib/orgSettings";
import { Button } from "../ui/Button";
import { Input } from "../ui/Field";

interface Person {
  employee_id: string;
  name: string;
  sold_cents: number;
  sales: number;
  target_cents: number;
  me: boolean;
}
interface Month {
  month: string;
  people: Person[];
  sold_cents: number;
  target_cents: number;
}

const pct = (sold: number, target: number) => (target > 0 ? Math.min(100, Math.round((sold / target) * 100)) : 0);

function Bar({ sold, target }: { sold: number; target: number }) {
  if (target <= 0) return null;
  const p = pct(sold, target);
  return (
    <div className="minions-target" role="progressbar" aria-valuenow={p} aria-valuemin={0} aria-valuemax={100} aria-label="Of target">
      <span style={{ width: `${p}%` }} className={p >= 100 ? "met" : ""} />
    </div>
  );
}

/** Sales this month against target. `mine`: just my own line (Today);
 * otherwise everyone I look after, with targets I can set (Team). */
export function TeamSales({ mine = false }: { mine?: boolean }) {
  const [data, setData] = useState<Month | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [value, setValue] = useState("");
  const load = useCallback(() => {
    api
      .get<Month>("/api/minions/team/sales")
      .then(setData)
      .catch(() => setData(null));
  }, []);
  useEffect(load, [load]);

  async function save(p: Person) {
    const cents = Math.round(Number(value || 0) * 100);
    if (!Number.isFinite(cents) || cents < 0) return;
    await api.put(`/api/minions/team/targets/${p.employee_id}`, { sales_target_cents: cents }).catch(() => {});
    setEditing(null);
    load();
  }

  if (!data) return null;
  const people = mine ? data.people.filter((p) => p.me) : data.people.filter((p) => !p.me);
  if (!people.length) return null;
  if (mine) {
    const [me] = people;
    if (!me.sales && !me.target_cents) return null;
    return (
      <section aria-label="My sales this month">
        <h2 className="minions-group">My sales this month</h2>
        <p className="minions-row-title">
          {formatMoney(me.sold_cents, { whole: true })}
          {me.target_cents ? ` of ${formatMoney(me.target_cents, { whole: true })} (${pct(me.sold_cents, me.target_cents)}%)` : ""}
        </p>
        <Bar sold={me.sold_cents} target={me.target_cents} />
      </section>
    );
  }
  const sold = people.reduce((s, p) => s + p.sold_cents, 0);
  const target = people.reduce((s, p) => s + p.target_cents, 0);
  return (
    <section aria-label="Sales this month">
      <h2 className="minions-group">
        Sales this month: {formatMoney(sold, { whole: true })}
        {target ? ` of ${formatMoney(target, { whole: true })} (${pct(sold, target)}%)` : ""}
      </h2>
      <Bar sold={sold} target={target} />
      <ul className="minions-rows">
        {people.map((p) => (
          <li key={p.employee_id} className="minions-row">
            <div className="minions-row-main">
              <span className="minions-row-title">{p.name}</span>
              <span className="field-label">
                {formatMoney(p.sold_cents, { whole: true })} from {p.sales} {p.sales === 1 ? "sale" : "sales"}
                {p.target_cents ? `, ${pct(p.sold_cents, p.target_cents)}% of ${formatMoney(p.target_cents, { whole: true })}` : ", no target"}
              </span>
              <Bar sold={p.sold_cents} target={p.target_cents} />
            </div>
            {editing === p.employee_id ? (
              <form
                className="minions-actions"
                onSubmit={(e) => {
                  e.preventDefault();
                  save(p);
                }}
              >
                <Input type="number" min={0} step="1" inputMode="numeric" aria-label={`Monthly target for ${p.name}`} value={value} onChange={(e) => setValue(e.target.value)} />
                <Button size="sm" type="submit" variant="primary">
                  Save
                </Button>
              </form>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setEditing(p.employee_id);
                  setValue(p.target_cents ? String(p.target_cents / 100) : "");
                }}
              >
                {p.target_cents ? "Change target" : "Set target"}
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
