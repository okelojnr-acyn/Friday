import { describe, expect, it } from "vitest";
import { countDiffs } from "./StockTakePage";

describe("countDiffs", () => {
  const p = (id: string, on: number, cost = 100) => ({ id, on_hand_qty: on, cost_cents: cost });
  it("keeps only real differences, valued at cost", () => {
    const d = countDiffs([p("a", 10), p("b", 5), p("c", 3)], { a: "8", b: "5", c: "" });
    expect(d.map((x) => [x.p.id, x.delta, x.value])).toEqual([["a", -2, -200]]);
  });
  it("never reads a typo or a negative as zero", () => {
    expect(countDiffs([p("a", 10)], { a: "1o" })).toEqual([]);
    expect(countDiffs([p("a", 10)], { a: "-1" })).toEqual([]);
  });
});
