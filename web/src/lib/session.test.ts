import { afterEach, describe, expect, it, vi } from "vitest";
import { takeFreshSignIn } from "./session";

describe("takeFreshSignIn", () => {
  const store = new Map<string, string>();
  vi.stubGlobal("sessionStorage", {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => store.set(k, v),
    removeItem: (k: string) => store.delete(k),
  });
  afterEach(() => store.clear());

  it("counts a sign-in from the last two minutes, once", () => {
    store.set("friday.signedInAt", String(1_000_000));
    expect(takeFreshSignIn(1_000_000 + 60_000)).toBe(true);
    expect(takeFreshSignIn(1_000_000 + 60_000)).toBe(false); // used up
  });
  it("ignores an old or missing one", () => {
    store.set("friday.signedInAt", String(1_000_000));
    expect(takeFreshSignIn(1_000_000 + 3 * 60_000)).toBe(false);
    expect(takeFreshSignIn()).toBe(false);
  });
});
