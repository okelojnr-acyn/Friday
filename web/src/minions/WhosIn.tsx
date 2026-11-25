import { useEffect, useState } from "react";
import { api } from "../lib/api";

interface Row {
  employee_id: string;
  name: string;
  department: string;
  state: "in" | "away" | "not_yet";
  till?: string;
  since?: string | null;
  last_seen?: string | null;
  leave?: "annual" | "sick" | "unpaid";
}

const time = (iso?: string | null) => (iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "");
const LEAVE = { annual: "on annual leave", sick: "off sick", unpaid: "on unpaid leave" } as const;

/** Team > Who's in today: the people I look after, from till sign-ins and
 * Friday or Minions opened today, and approved time off. There's no
 * clock-out, so it says when they were last seen. */
export function WhosIn() {
  const [rows, setRows] = useState<Row[] | null>(null);
  useEffect(() => {
    api
      .get<Row[]>("/api/minions/team/today")
      .then(setRows)
      .catch(() => setRows(null));
  }, []);
  if (!rows || rows.length === 0) return null;
  const counts = { in: 0, away: 0, not_yet: 0 };
  rows.forEach((r) => counts[r.state]++);
  return (
    <section aria-label="Who's in today">
      <h2 className="minions-group">
        Who's in today: {counts.in} in{counts.away ? `, ${counts.away} away` : ""}
        {counts.not_yet ? `, ${counts.not_yet} not seen yet` : ""}
      </h2>
      <ul className="minions-rows">
        {rows.map((r) => (
          <li key={r.employee_id} className="minions-row">
            <span className={`minions-presence ${r.state}`} aria-hidden="true" />
            <div className="minions-row-main">
              <span className="minions-row-title">{r.name}</span>
              <span className="field-label">
                {r.state === "in"
                  ? [r.till ? `At ${r.till}` : "On Friday", r.since ? `since ${time(r.since)}` : "", r.last_seen ? `last seen ${time(r.last_seen)}` : ""]
                      .filter(Boolean)
                      .join(", ")
                  : r.state === "away"
                    ? LEAVE[r.leave ?? "annual"]
                    : "Not seen yet today"}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
