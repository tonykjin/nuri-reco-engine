import { describe, expect, it } from "vitest";

import { stageLabel, stageRuleIds, type TraceStage } from "./trace";

const stage = (over: Partial<TraceStage>): TraceStage => ({
  stage: "targets",
  rule_ids: [],
  inputs: {},
  outputs: {},
  children: [],
  ...over,
});

describe("stageRuleIds", () => {
  it("lists a stage's rules, then its children's, without repeats", () => {
    const parent = stage({
      rule_ids: ["A.B"],
      children: [stage({ rule_ids: ["C.D", "A.B"] }), stage({ rule_ids: ["E.F"] })],
    });
    expect(stageRuleIds(parent)).toEqual(["A.B", "C.D", "E.F"]);
  });
});

describe("stageLabel", () => {
  it("names top-level stages and per-phase children", () => {
    expect(stageLabel(stage({ stage: "safety" }))).toBe("Safety · Matrix F");
    expect(stageLabel(stage({ inputs: { phase: { name: "step_back" } } }), true)).toBe(
      "Phase: step back",
    );
    expect(stageLabel(stage({ stage: "new_stage" }))).toBe("new_stage");
  });
});
