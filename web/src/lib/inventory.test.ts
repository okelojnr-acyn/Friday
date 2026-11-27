import { describe, expect, it } from "vitest";
import { shortWarning } from "./inventory";

describe("shortWarning", () => {
  const rice = { name: "Rice 2KG", on_hand_qty: 3, track_inventory: true };
  it("is quiet while there's enough, or when stock isn't counted", () => {
    expect(shortWarning(rice, 3)).toBeNull();
    expect(shortWarning({ ...rice, track_inventory: false }, 10)).toBeNull();
  });
  it("warns past the shelf, in sales units", () => {
    expect(shortWarning(rice, 4)).toMatch(/Only 3 Rice 2KG/);
    // A crate of 12 with 20 bottles on record: one crate fits, two don't.
    const crate = { name: "Soda crate", on_hand_qty: 20, track_inventory: true, sales_factor: 12 };
    expect(shortWarning(crate, 1)).toBeNull();
    expect(shortWarning(crate, 2)).toMatch(/Only 1 Soda crate/);
  });
});
