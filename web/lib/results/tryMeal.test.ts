import { describe, expect, it } from "vitest";

import { canScore, componentLabel, readyItems } from "./tryMeal";

describe("readyItems", () => {
  it("keeps rows with a food and positive grams", () => {
    expect(
      readyItems([
        { key: "apple", grams: 182 },
        { key: null, grams: 100 },
        { key: "rice_white_cooked", grams: 0 },
      ]),
    ).toEqual([{ key: "apple", grams: 182 }]);
  });
});

describe("canScore", () => {
  const row = (key: string) => ({ key, grams: 100 });
  it("needs 2-4 complete, distinct foods", () => {
    expect(canScore([row("a")])).toBe(false);
    expect(canScore([row("a"), row("b")])).toBe(true);
    expect(canScore([row("a"), row("b"), row("c"), row("d")])).toBe(true);
    expect(canScore([row("a"), row("b"), row("c"), row("d"), row("e")])).toBe(false);
    expect(canScore([row("a"), row("a")])).toBe(false);
    expect(canScore([row("a"), { key: "b", grams: null }])).toBe(false);
  });
});

describe("componentLabel", () => {
  it("labels components and micronutrients", () => {
    expect(componentLabel("sat_fat")).toBe("Saturated fat");
    expect(componentLabel("vitamin_b12")).toBe("Vitamin B12");
    expect(componentLabel("iron")).toBe("Iron");
  });
});
