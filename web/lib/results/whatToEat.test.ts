import { describe, expect, it } from "vitest";

import { foodContext, upsertPantry } from "./whatToEat";

describe("upsertPantry", () => {
  it("adds a food once and updates it in place", () => {
    const one = upsertPantry([], { key: "banana", ripeness: "ripe", peaks_tonight: false });
    expect(one).toHaveLength(1);
    const two = upsertPantry(one, { key: "banana", ripeness: "peak", peaks_tonight: true });
    expect(two).toEqual([{ key: "banana", ripeness: "peak", peaks_tonight: true }]);
    expect(upsertPantry(two, { key: "kiwi", peaks_tonight: false })).toHaveLength(2);
  });
});

describe("foodContext", () => {
  it("passes the filters and pantry through unchanged", () => {
    const pantry = [{ key: "banana", peaks_tonight: true }];
    expect(foodContext("snack", "long", "base", pantry)).toEqual({
      meal_slot: "snack",
      day_type: "long",
      phase: "base",
      pantry,
    });
  });
});
