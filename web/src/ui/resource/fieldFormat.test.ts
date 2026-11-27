import { describe, expect, it } from "vitest";
import { fullDate, humanize, isOverdue, shortDate } from "./fieldFormat";

describe("shortDate", () => {
  it("keeps a calendar day on its own day, with no seconds", () => {
    expect(shortDate("2026-11-25", false)).toMatch(/25/);
    expect(shortDate("2026-11-25", false)).not.toMatch(/24/);
    expect(shortDate("2025-11-27T10:17:42Z", true)).not.toMatch(/42|10:17/);
    expect(shortDate(new Date().toISOString(), true)).toMatch(/\d{1,2}:\d{2}/);
  });
  it("passes through what isn't a date", () => {
    expect(shortDate("soon", false)).toBe("soon");
  });
});

describe("isOverdue", () => {
  const due = { name: "due_at", type: "date" } as unknown as Parameters<typeof isOverdue>[0];
  const past = "2020-01-01";
  it("a void, draft or paid invoice is never overdue", () => {
    for (const status of ["void", "draft", "paid", "cancelled"]) {
      expect(isOverdue(due, { due_at: past, status })).toBe(false);
    }
    expect(isOverdue(due, { due_at: past, status: "sent" })).toBe(true);
  });
  it("trusts the server's is_overdue when it sends one", () => {
    expect(isOverdue(due, { due_at: past, status: "sent", is_overdue: false })).toBe(false);
  });
});

describe("words", () => {
  it("humanizes stored values and writes full dates without seconds", () => {
    expect(humanize("in_progress")).toBe("In progress");
    expect(fullDate("2026-11-27T09:53:42Z")).not.toMatch(/:42|\d+\/\d+\//);
  });
});
