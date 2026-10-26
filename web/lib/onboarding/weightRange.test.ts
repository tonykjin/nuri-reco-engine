import { describe, expect, it } from "vitest";

import { mapAnswers } from "./mapAnswers";
import { PERSONAS } from "./personas";
import {
  fromDisplay,
  inBand,
  sliderModel,
  snap,
  type TargetBounds,
  toDisplay,
  withoutTargets,
} from "./weightRange";

// The engine's answer for a 30-year-old woman, 168 cm, 76 kg, losing fat (Task 25 tests).
const bounds: TargetBounds = {
  min_kg: 52.3,
  max_kg: 76,
  step_kg: 0.5,
  default_kg: 72.2,
  provenance: "recommended",
  rule_ids: ["WEIGHT.RANGE.SLIDER", "GUARD.ED_RISK"],
  why: "We suggest starting about 5% below your current weight.",
};
const recommended = { min_kg: 52.3, max_kg: 70.2 };

describe("units", () => {
  it("round-trips kg and lb within 0.1", () => {
    for (const kg of [45.3, 52.3, 70.2, 120]) {
      expect(fromDisplay(toDisplay(kg, "imperial"), "imperial")).toBeCloseTo(kg, 1);
      expect(toDisplay(kg, "metric")).toBe(kg);
    }
  });
});

describe("sliderModel", () => {
  it("rounds the engine's bounds inward to the 0.5 kg grid and snaps the default", () => {
    const m = sliderModel(bounds, recommended, null, "metric");
    expect(m).toMatchObject({ min: 52.5, max: 76, step: 0.5, defaultValue: 72 });
  });

  it("uses whole pounds in imperial, still inside the engine's bounds", () => {
    const m = sliderModel(bounds, recommended, null, "imperial");
    expect(m.step).toBe(1);
    expect(m.min).toBe(116); // 52.3 kg = 115.3 lb, rounded up
    expect(m.max).toBe(167); // 76 kg = 167.6 lb, rounded down
    expect(fromDisplay(m.min, "imperial")).toBeGreaterThanOrEqual(bounds.min_kg);
    expect(fromDisplay(m.max, "imperial")).toBeLessThanOrEqual(bounds.max_kg);
    expect(m.defaultValue).toBe(159); // 72.2 kg = 159.2 lb
  });

  it("places the recommended band by percent along the slider", () => {
    const m = sliderModel(bounds, recommended, null, "metric");
    expect(m.bands).toHaveLength(1);
    expect(m.bands[0].kind).toBe("recommended");
    expect(m.bands[0].fromPct).toBe(0); // 52.3 is below the slider's 52.5
    expect(m.bands[0].toPct).toBeCloseTo(((70.2 - 52.5) / (76 - 52.5)) * 100, 6);
  });

  it("clips bands to the slider and drops ones outside it", () => {
    const big = { ...bounds, min_kg: 70, max_kg: 120, default_kg: 114 };
    const m = sliderModel(big, recommended, { min_kg: 108, max_kg: 114 }, "metric");
    const rec = m.bands.find((b) => b.kind === "recommended");
    expect(rec?.fromPct).toBe(0);
    expect(m.bands.find((b) => b.kind === "milestone")).toMatchObject({
      fromPct: ((108 - 70) / 50) * 100,
      toPct: ((114 - 70) / 50) * 100,
    });
    const above = sliderModel(big, { min_kg: 30, max_kg: 40 }, null, "metric");
    expect(above.bands).toEqual([]);
  });
});

describe("snap", () => {
  const model = { min: 52.5, max: 76, step: 0.5 };

  it("rounds to the step and clamps to the bounds", () => {
    expect(snap(72.2, model)).toBe(72);
    expect(snap(72.3, model)).toBe(72.5);
    expect(snap(10, model)).toBe(52.5);
    expect(snap(99, model)).toBe(76);
  });
});

describe("inBand", () => {
  it("compares in kg whatever the display units", () => {
    expect(inBand(70, recommended, "metric")).toBe(true);
    expect(inBand(72, recommended, "metric")).toBe(false);
    expect(inBand(154, recommended, "imperial")).toBe(true); // 69.9 kg
    expect(inBand(70, null, "metric")).toBe(false);
  });
});

describe("withoutTargets", () => {
  it("clears every target and changes nothing else", () => {
    const { answers, as_of } = PERSONAS.goal_bmi_low;
    const request = mapAnswers(answers, { asOf: as_of });
    const cleared = withoutTargets(request);
    expect(cleared.goals.map((g) => g.target_weight_kg)).toEqual([null]);
    expect({ ...cleared, goals: request.goals }).toEqual(request);
  });
});
