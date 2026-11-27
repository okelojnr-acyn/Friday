import { describe, expect, it } from "vitest";
import { overridesNeedingApproval } from "./overrides";

const shelf = (id: string) => ({ rice: 48_000 })[id as "rice"];
const line = (over: Partial<{ unit_price_cents: number; discount_bp: number }>) => ({
  description: "Rice",
  product_id: "rice",
  unit_price_cents: 48_000,
  discount_bp: 0,
  ...over,
});

describe("overridesNeedingApproval", () => {
  it("lets shelf prices and small discounts through", () => {
    expect(overridesNeedingApproval([line({ discount_bp: 500 })], shelf, "member")).toEqual([]);
  });
  it("asks for a lowered price or 10% off and more, from cashiers only", () => {
    expect(overridesNeedingApproval([line({ unit_price_cents: 40_000 })], shelf, "member")).toEqual(["Rice: price lowered"]);
    expect(overridesNeedingApproval([line({ discount_bp: 1000 })], shelf, "member")).toEqual(["Rice: 10% off"]);
    expect(overridesNeedingApproval([line({ discount_bp: 5000 })], shelf, "branch_manager")).toEqual([]);
  });
  it("follows the business's own limit", () => {
    expect(overridesNeedingApproval([line({ discount_bp: 500 })], shelf, "member", 500)).toEqual(["Rice: 5% off"]);
    expect(overridesNeedingApproval([line({ discount_bp: 0 })], shelf, "member", 0)).toEqual([]);
  });
  it("a raised price or an item not on the shelf needs no one", () => {
    expect(overridesNeedingApproval([line({ unit_price_cents: 50_000 })], shelf, "member")).toEqual([]);
    expect(overridesNeedingApproval([{ ...line({ unit_price_cents: 1 }), product_id: null }], shelf, "member")).toEqual([]);
  });
});
