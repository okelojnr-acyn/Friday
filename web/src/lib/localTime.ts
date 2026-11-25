/** Local time (owner, 2026-11-25): the server stores UTC; screens show and
 * pick dates and times in the viewer's own time zone. */

const pad = (n: number) => String(n).padStart(2, "0");

/** YYYY-MM-DD of `d` in the viewer's calendar (toISOString gives UTC's). */
export function localDay(d: Date = new Date()): string {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** A server value for an <input type="date">: a timestamp becomes the
 * viewer's date; a bare YYYY-MM-DD stays as it is. */
export function toLocalDateInput(value: unknown): string {
  if (typeof value !== "string" || !value) return "";
  if (!value.includes("T")) return value.slice(0, 10);
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value.slice(0, 10) : localDay(d);
}

/** A server timestamp for an <input type="datetime-local">, in local time. */
export function toLocalDatetimeInput(value: unknown): string {
  if (typeof value !== "string" || !value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value.slice(0, 16);
  return `${localDay(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** An <input type="datetime-local"> value (local, no zone) as UTC ISO. */
export function fromLocalDatetimeInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value); // a zone-less date-time is read as local time
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** The viewer's IANA time zone ("Africa/Nairobi"), "" if the browser won't say. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}
