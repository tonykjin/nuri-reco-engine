// Decision trace: POST /v1/plan/trace. The engine records the stages and rules; this file only
// fetches and labels them.

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { PlanRequest } from "@/lib/onboarding/mapAnswers";

export type TracedPlan = components["schemas"]["TracedPlan"];
export type Trace = components["schemas"]["Trace"];
export type TraceStage = components["schemas"]["TraceStage"];
export type TraceRule = components["schemas"]["TraceRule"];

export async function fetchTrace(
  request: PlanRequest,
  simulateHistory: boolean,
  signal?: AbortSignal,
): Promise<TracedPlan> {
  const { data, error } = await api.POST("/v1/plan/trace", {
    body: { request, simulate_history: simulateHistory },
    signal,
  });
  if (error || !data) {
    const message = (error as { error?: { message?: string } } | undefined)?.error?.message;
    throw new Error(message ?? "The trace service didn't respond.");
  }
  return data;
}

export const STAGE_LABELS: Record<string, string> = {
  simulation: "Simulated logs (demo)",
  safety: "Safety · Matrix F",
  goals: "Goals · Matrix A/B",
  feasibility: "Feasibility · §4.4",
  expenditure: "Expenditure",
  targets: "Targets · per phase",
  score_profile: "Loam Score profile · Matrix G",
  patterns: "Diet patterns · Matrix D",
  foods: "Foods · Matrix E",
  summary: "Goal summary · §7b.6",
};

/** A child stage's heading: the phase it covers, when it has one. */
export function stageLabel(stage: TraceStage, child = false): string {
  const label = STAGE_LABELS[stage.stage] ?? stage.stage;
  if (!child) return label;
  const phase = (stage.inputs as { phase?: { name?: string } }).phase?.name;
  return phase ? `Phase: ${phase.replaceAll("_", " ")}` : label;
}

/** Every rule id under a stage, its children included, in order of first use. */
export function stageRuleIds(stage: TraceStage): string[] {
  const ids = [...(stage.rule_ids ?? []), ...(stage.children ?? []).flatMap(stageRuleIds)];
  return [...new Set(ids)];
}
