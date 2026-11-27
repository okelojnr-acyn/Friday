import { describe, expect, it } from "vitest";
import type { FieldSpec, RecordRow } from "../../lib/types";
import { dayField } from "./ListView";

const created = { name: "created_at", type: "datetime" } as FieldSpec;
const rows = (dates: string[]) => dates.map((d, i) => ({ id: String(i), created_at: d }) as RecordRow);

describe("dayField", () => {
  it("groups a list in date order", () => {
    const r = rows(["2026-11-27T10:00Z", "2026-11-27T09:00Z", "2026-11-26T09:00Z", "2026-11-25T09:00Z", "2026-11-20T09:00Z"]);
    expect(dayField([created], r)).toBe(created);
  });
  it("never groups an unordered list, a short one, or one with blank dates", () => {
    expect(dayField([created], rows(["2026-11-20", "2026-11-27", "2026-11-21", "2026-11-25", "2026-11-22"]))).toBeNull();
    expect(dayField([created], rows(["2026-11-27", "2026-11-26"]))).toBeNull();
    expect(dayField([created], rows(["2026-11-27", "", "2026-11-25", "2026-11-24", "2026-11-23"]))).toBeNull();
  });
});
