const TONE: Record<string, string> = {
  low: "priority-low",
  medium: "priority-medium",
  high: "priority-high",
  urgent: "priority-urgent",
};

/** A small filled dot + the label, colored by rank -- cheaper to scan
 * than re-reading a select value on every card, and the same vocabulary
 * (low/medium/high/urgent) is reused across CRM and Projects. */
export function PriorityFlag({ value }: { value: string }) {
  const cls = TONE[value.toLowerCase()] ?? "priority-medium";
  return (
    <span className={`priority-flag ${cls}`}>
      <span className="priority-dot" />
      {value}
    </span>
  );
}
