import { describe, expect, it } from "vitest";

import {
  byDayOrder,
  dateRange,
  mealPattern,
  referralTitle,
  ruleIds,
  target,
  weight,
} from "./format";

const t = (patch: object) => ({ unit: "g", low: null, high: null, min: null, max: null, ...patch });

describe("score targets", () => {
  it("formats ranges, floors and caps as the engine sent them", () => {
    expect(target(t({ low: 112, high: 154 }))).toBe("112–154 g");
    expect(target(t({ min: 25.8363 }))).toBe("at least 26 g");
    expect(target(t({ unit: "mg", max: 2300 }))).toBe("at most 2,300 mg");
    expect(target(t({ unit: "mcg", min: 2.4 }))).toBe("at least 2.4 mcg");
    expect(target(t({ unit: "mcg_dfe", min: 400 }))).toBe("at least 400 mcg DFE");
  });
});

describe("display units", () => {
  it("shows kg, or lb for imperial users", () => {
    expect(weight(68.1, "metric")).toBe("68.1 kg");
    expect(weight(68.1, "imperial")).toBe("150.1 lb");
  });

  it("formats phase dates", () => {
    expect(dateRange("2026-10-16", "2026-12-27")).toBe("16 Oct 2026 – 27 Dec 2026");
    expect(dateRange("2027-05-03", null)).toBe("from 3 May 2027");
  });
});

describe("referrals", () => {
  it("names who to talk to, and has its own title for support resources", () => {
    expect(referralTitle(["rd"])).toBe("Talk to a registered dietitian");
    expect(referralTitle(["family", "clinician"])).toBe(
      "Talk to a parent or guardian or your doctor",
    );
    expect(referralTitle(["doctor", "clinician"])).toBe("Talk to your doctor");
    expect(referralTitle(["resources"])).toBe("Where to find support");
  });
});

describe("day tabs", () => {
  it("orders day types rest, easy, quality, long", () => {
    expect(["rest", "quality", "easy", "long"].sort(byDayOrder)).toEqual([
      "rest",
      "easy",
      "quality",
      "long",
    ]);
  });
});

describe("dev drawer rule ids", () => {
  it("collects rule ids from anywhere in the response, once each", () => {
    const response = {
      safety: { warnings: [{ rule_id: "GUARD.X", rule_ids: ["GUARD.X", "COMBO.Y"] }] },
      loam_score_profile: {
        weight_rule_ids: ["LSW.ROW"],
        by_phase: [{ weight_rule_ids: ["LSW.ROW"] }],
      },
    };
    expect(ruleIds(response)).toEqual(["GUARD.X", "COMBO.Y", "LSW.ROW"]);
  });
});

describe("meal pattern", () => {
  const mp = (meals: number, snacks: number, source: "user" | "default" = "user") => ({
    meals,
    snacks,
    source,
    per_meal_protein_g: 35,
    provenance: "recommended" as const,
    rule_ids: ["TIMING.MEAL_PATTERN"],
    why: "Your protein is spread across your meals.",
  });

  it("names meals and snacks, with singulars and no snack part when there are none", () => {
    expect(mealPattern(mp(3, 1))).toBe("3 meals + 1 snack");
    expect(mealPattern(mp(2, 2))).toBe("2 meals + 2 snacks");
    expect(mealPattern(mp(1, 0))).toBe("1 meal");
  });

  it("says when the engine used its default", () => {
    expect(mealPattern(mp(3, 1, "default"))).toBe("3 meals + 1 snack (our default)");
  });
});
