import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { type Answers, initialAnswers } from "./answers";
import { ageOn, heightCm, mapAnswers, scoffScore, toKg } from "./mapAnswers";
import { PERSONAS } from "./personas";

const ENGINE_PERSONAS = new URL("../../../engine/tests/personas/", import.meta.url);

function engineRequest(name: string) {
  const raw = JSON.parse(
    readFileSync(fileURLToPath(new URL(`${name}.json`, ENGINE_PERSONAS)), "utf8"),
  );
  delete raw.expect;
  return raw;
}

describe("mapAnswers matches the engine persona requests", () => {
  it("has all 10 personas", () => {
    expect(Object.keys(PERSONAS)).toHaveLength(10);
  });

  it.each(Object.keys(PERSONAS))("%s", (name) => {
    const { as_of, answers } = PERSONAS[name];
    expect(mapAnswers(answers, { asOf: as_of })).toStrictEqual(engineRequest(name));
  });
});

describe("age from birth date", () => {
  it.each([
    ["1996-10-16", "2026-10-16", 30], // birthday today
    ["1996-10-17", "2026-10-16", 29], // birthday tomorrow
    ["1996-11-01", "2026-10-16", 29], // later month
    ["1996-01-31", "2026-10-16", 30], // earlier month
    ["2008-02-29", "2026-02-28", 17], // leap-day birthday, not yet
    ["2008-02-29", "2026-03-01", 18],
  ])("born %s, on %s -> %i", (birth, asOf, age) => {
    expect(ageOn(birth, asOf)).toBe(age);
  });
});

describe("unit conversion", () => {
  it("leaves metric values as entered", () => {
    expect(toKg(70.25, "metric")).toBe(70.25);
    expect(
      heightCm({
        units: "metric",
        heightCm: 168.5,
        heightFt: null,
        heightIn: null,
      }),
    ).toBe(168.5);
  });

  it("converts pounds to kg (0.1 kg)", () => {
    expect(toKg(154.3, "imperial")).toBe(70);
    expect(toKg(200, "imperial")).toBe(90.7);
  });

  it("converts feet and inches to cm (whole cm)", () => {
    const h = (ft: number, inches: number | null) =>
      heightCm({
        units: "imperial",
        heightCm: null,
        heightFt: ft,
        heightIn: inches,
      });
    expect(h(5, 6)).toBe(168);
    expect(h(6, 0)).toBe(183);
    expect(h(6, null)).toBe(183);
  });
});

describe("field mapping", () => {
  const base: Answers = {
    ...initialAnswers,
    goals: ["lose_fat"],
    sex: "female",
    birthDate: "1990-01-01",
    weight: 70,
    heightCm: 168,
    activity: "mostly_sitting",
    health: {
      ...initialAnswers.health,
      scoff: [false, false, false, false, false],
    },
  };
  const map = (patch: Partial<Answers>) =>
    mapAnswers({ ...base, ...patch }, { asOf: "2026-10-16" });

  it("ranks goals by the user's order, then choice order", () => {
    const r = map({ goals: ["both", "event"], ranking: ["endurance_event"] });
    expect(r.goals.map((g) => [g.type, g.priority])).toEqual([
      ["endurance_event", 1],
      ["lose_fat", 2],
      ["build_muscle", 3],
    ]);
  });

  it("drops duplicate goal types", () => {
    expect(map({ goals: ["lose_fat", "both"] }).goals.map((g) => g.type)).toEqual([
      "lose_fat",
      "build_muscle",
    ]);
  });

  it("puts the pace on weight goals only", () => {
    const r = map({ goals: ["lose_fat", "event"], pace: 0.5 });
    expect(r.goals.map((g) => g.rate_pct_bw_week)).toEqual([0.5, null]);
  });

  it("sends SCOFF as a count, or null if any item is unanswered", () => {
    expect(scoffScore([true, false, true, false, false])).toBe(2);
    expect(scoffScore([true, null, false, false, false])).toBeNull();
    expect(map({}).profile.flags?.scoff_score).toBe(0);
  });

  it("splits eating style into diet and pattern", () => {
    expect(map({ eatingStyle: "vegan" }).constraints).toMatchObject({
      diet: "vegan",
    });
    expect(map({ eatingStyle: "lower_carb" }).preferences).toMatchObject({
      pattern_pref: "low_carb_keto",
    });
    const balanced = map({ eatingStyle: "balanced" });
    expect([balanced.constraints?.diet, balanced.preferences?.pattern_pref]).toEqual([null, null]);
  });

  it("maps pregnancy answers to flags", () => {
    const flags = (pregnancy: Answers["health"]["pregnancy"]) =>
      map({ health: { ...base.health, pregnancy } }).profile.flags;
    expect(flags("pregnant")).toMatchObject({
      pregnant: true,
      breastfeeding: false,
    });
    expect(flags("breastfeeding")).toMatchObject({
      pregnant: false,
      breastfeeding: true,
    });
    expect(flags("prefer_not_to_say")).toMatchObject({
      pregnant: false,
      breastfeeding: false,
    });
  });

  it("refuses to guess a missing answer", () => {
    expect(() => map({ birthDate: null })).toThrow("missing answer: birth date");
    expect(() => map({ goals: [] })).toThrow("missing answer: goals");
  });
});
