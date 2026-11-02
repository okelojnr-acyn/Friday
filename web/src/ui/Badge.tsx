interface BadgeProps {
  children: string;
  tone?: "neutral" | "success" | "danger" | "accent";
}

const TONE_CLASS: Record<NonNullable<BadgeProps["tone"]>, string> = {
  neutral: "badge",
  success: "badge badge-success",
  danger: "badge badge-danger",
  accent: "badge badge-accent",
};

/** Picks a sensible tone for common status vocab (won/paid/synced ->
 * success; lost/void/overdue -> danger) without the caller having to
 * know every app's status strings up front. */
export function statusTone(value: string): BadgeProps["tone"] {
  const v = value.toLowerCase();
  if (["won", "paid", "synced", "resolved", "closed", "done"].includes(v)) return "success";
  if (["lost", "void", "overdue", "cancelled", "urgent"].includes(v)) return "danger";
  if (["new", "open", "draft"].includes(v)) return "accent";
  return "neutral";
}

export function Badge({ children, tone = "neutral" }: BadgeProps) {
  return <span className={TONE_CLASS[tone]}>{children}</span>;
}
