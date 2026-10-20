import { describe, expect, it } from "vitest";

import { type Answers, initialAnswers } from "./answers";
import { PERSONAS } from "./personas";
import { nextStep, previousStep, STEP_IDS, visibleSteps } from "./steps";

const ids = (answers: Answers) => visibleSteps(answers).map((s) => s.id);

describe("onboarding steps", () => {
  it("has the 14 screens of spec 11.3, ending in results", () => {
    expect(STEP_IDS).toHaveLength(14);
    expect(STEP_IDS.at(-1)).toBe("results");
    expect(new Set(STEP_IDS).size).toBe(14);
  });

  it("skips ranking with one goal, and details and pace without weight or event goals", () => {
    const visible = ids({ ...initialAnswers, goals: ["eat_healthier"] });
    expect(visible).not.toContain("priority");
    expect(visible).not.toContain("goal-details");
    expect(visible).not.toContain("pace");
    expect(visible).toHaveLength(11);
  });

  it("shows ranking when one choice adds two goals", () => {
    expect(ids({ ...initialAnswers, goals: ["both"] })).toContain("priority");
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
    expect(nextStep("results", answers)).toBeUndefined();
  });
});
