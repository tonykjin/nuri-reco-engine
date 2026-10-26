import { describe, expect, it } from "vitest";

import { type Answers, initialAnswers } from "./answers";
import { PERSONAS } from "./personas";
import { nextStep, previousStep, STEP_IDS, STEPS, visibleSteps } from "./steps";

const ids = (answers: Answers) => visibleSteps(answers).map((s) => s.id);

describe("onboarding steps", () => {
  it("has screens 1-14 of spec 11.3, ending in building", () => {
    expect(STEP_IDS).toHaveLength(14);
    expect(STEP_IDS.at(-1)).toBe("building");
    expect(new Set(STEP_IDS).size).toBe(14);
  });

  it("asks for the target weight right after the health check", () => {
    const at = STEP_IDS.indexOf("target-weight");
    expect(STEP_IDS.slice(at - 1, at + 2)).toEqual(["health", "target-weight", "eating"]);
    expect(STEP_IDS.indexOf("about")).toBeLessThan(at);
    expect(STEP_IDS.indexOf("activity")).toBeLessThan(at);
  });

  it("shows target weight only for weight goals, and goal details only for events", () => {
    const lose = ids({ ...initialAnswers, goals: ["lose_fat"] });
    expect(lose).toContain("target-weight");
    expect(lose).not.toContain("goal-details");
    expect(ids({ ...initialAnswers, goals: ["gain_weight"] })).toContain("target-weight");
    const race = ids({ ...initialAnswers, goals: ["event"] });
    expect(race).toContain("goal-details");
    expect(race).not.toContain("target-weight");
    expect(ids({ ...initialAnswers, goals: ["date"] })).toContain("goal-details");
  });

  it("only 'eat healthier' skips ranking, goal details and pace", () => {
    const visible = ids({ ...initialAnswers, goals: ["eat_healthier"] });
    expect(visible).not.toContain("priority");
    expect(visible).not.toContain("goal-details");
    expect(visible).not.toContain("target-weight");
    expect(visible).not.toContain("pace");
    expect(visible).toHaveLength(10);
  });

  it("shows ranking when one choice adds two goals", () => {
    expect(ids({ ...initialAnswers, goals: ["both"] })).toContain("priority");
  });

  it("shows pace for lose fat but not for gain weight", () => {
    expect(ids({ ...initialAnswers, goals: ["lose_fat"] })).toContain("pace");
    expect(ids({ ...initialAnswers, goals: ["gain_weight"] })).not.toContain("pace");
  });

  it("shows every screen for the marathon persona", () => {
    expect(ids(PERSONAS.marathon_fatloss.answers)).toEqual(STEP_IDS);
  });

  it("Back and Continue skip hidden steps", () => {
    const answers: Answers = { ...initialAnswers, goals: ["eat_healthier"] };
    expect(nextStep("goals", answers)?.id).toBe("about");
    expect(previousStep("about", answers)?.id).toBe("goals");
    expect(nextStep("taste", answers)?.id).toBe("building");
    expect(previousStep("welcome", answers)).toBeUndefined();
    expect(nextStep("building", answers)).toBeUndefined();
  });

  it.each(Object.keys(PERSONAS))("%s can step through every screen", (name) => {
    // Prefill -> step through: every visible screen accepts the persona's answers.
    const answers = PERSONAS[name].answers;
    const blocked = visibleSteps(answers)
      .filter((s) => s.complete && !s.complete(answers))
      .map((s) => s.id);
    expect(blocked).toEqual([]);
  });

  it("blocks Continue on empty answers where a screen needs input", () => {
    const blocked = STEPS.filter((s) => s.complete && !s.complete(initialAnswers)).map((s) => s.id);
    expect(blocked).toEqual(["welcome", "goals", "about", "activity", "health"]);
  });
});
