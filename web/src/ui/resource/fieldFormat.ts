import type { FieldSpec } from "../../lib/types";
import { statusTone } from "../Badge";

/** Cents (what every app stores) <-> a dollar-amount string (what a form
 * input shows). Keeps money as integers everywhere outside this one
 * conversion boundary. */
export function centsToAmountInput(cents: unknown): string {
  if (typeof cents !== "number") return "";
  return (cents / 100).toFixed(2);
}

export function amountInputToCents(value: string): number {
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

export function formatCellValue(field: FieldSpec, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  switch (field.type) {
    case "currency":
      return typeof value === "number" ? `$${(value / 100).toFixed(2)}` : String(value);
    case "boolean":
      return value ? "Yes" : "No";
    case "date":
      return typeof value === "string" ? new Date(value).toLocaleDateString() : String(value);
    case "datetime":
      return typeof value === "string" ? new Date(value).toLocaleString() : String(value);
    default:
      return String(value);
  }
}

export function toDateInputValue(value: unknown): string {
  if (typeof value !== "string" || !value) return "";
  return value.slice(0, 10);
}

export function toDatetimeInputValue(value: unknown): string {
  if (typeof value !== "string" || !value) return "";
  return value.slice(0, 16);
}

/** Heuristics the generic renderer uses to decide which fields earn a
 * richer treatment than a plain table cell -- an avatar for a person, a
 * flag for priority, a clock for a due date -- without every ResourceSpec
 * having to declare UI hints the backend shouldn't need to know about. */
export function isPersonField(field: FieldSpec): boolean {
  return field.type === "email" && field.name !== "created_by";
}

export function isDueDateField(field: FieldSpec): boolean {
  return (field.type === "date" || field.type === "datetime") && /due|next_step/i.test(field.name);
}

export function isPriorityField(field: FieldSpec): boolean {
  return field.name === "priority" && field.type === "select";
}

/** True for a due-date field whose date has passed on a record that
 * isn't already in a "done"-shaped state (reuses statusTone's success
 * vocabulary -- won/paid/synced/resolved/closed/done -- rather than a
 * second list of terminal statuses to keep in sync). Generic across
 * every app's resources the same way isPriorityField/isDueDateField
 * already are: a resource earns the "Overdue" treatment just by having a
 * `due_at`-shaped field and a `status` field, no extra config. */
export function isOverdue(field: FieldSpec, record: { [key: string]: unknown }): boolean {
  if (!isDueDateField(field)) return false;
  const raw = record[field.name];
  if (typeof raw !== "string" || !raw) return false;
  const due = new Date(raw).getTime();
  if (Number.isNaN(due) || due >= Date.now()) return false;
  const status = record.status;
  return !(typeof status === "string" && statusTone(status) === "success");
}

export function initials(value: unknown): string {
  const s = String(value ?? "").trim();
  if (!s) return "?";
  const namePart = s.includes("@") ? s.split("@")[0] : s;
  const pieces = namePart.split(/[.\s_-]+/).filter(Boolean);
  if (pieces.length >= 2) return (pieces[0][0] + pieces[1][0]).toUpperCase();
  return namePart.slice(0, 2).toUpperCase();
}

const PRIORITY_RANK: Record<string, number> = { low: 0, medium: 1, high: 2, urgent: 3 };

export function priorityRank(value: unknown): number {
  return PRIORITY_RANK[String(value ?? "").toLowerCase()] ?? 0;
}

export function sumCents(records: { [key: string]: unknown }[], field: FieldSpec): number {
  return records.reduce((total, r) => {
    const v = r[field.name];
    return total + (typeof v === "number" ? v : 0);
  }, 0);
}
