import { describe, expect, it } from "vitest";
import { shortDate } from "./fieldFormat";

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
