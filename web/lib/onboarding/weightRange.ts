// Target weight screen: POST /v1/goals/weight-range and the slider's display model.
// The engine sets the range, bounds, default and copy (spec §4.4b); this file only converts kg to
// the user's units and snaps to the slider's step.

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

import type { Answers } from "./answers";
import type { PlanRequest } from "./mapAnswers";
import { KG_PER_LB } from "./units";

export type WeightRangeResponse = components["schemas"]["WeightRangeResponse"];
export type TargetBounds = components["schemas"]["TargetBounds"];
type Band = { min_kg: number; max_kg: number };
type Units = Answers["units"];

/** Slider step in display units: the engine's step in kg, 1 lb in imperial. */
const LB_STEP = 1;

export async function fetchWeightRange(
  request: PlanRequest,
  signal?: AbortSignal,
): Promise<WeightRangeResponse> {
  const { data, error } = await api.POST("/v1/goals/weight-range", { body: request, signal });
  if (error || !data) {
    const message = (error as { error?: { message?: string } } | undefined)?.error?.message;
    throw new Error(message ?? "The weight range service didn't respond.");
  }
  return data;
}

/** The request without any target, so the range doesn't depend on an earlier pick. */
export function withoutTargets(request: PlanRequest): PlanRequest {
  return { ...request, goals: request.goals.map((g) => ({ ...g, target_weight_kg: null })) };
}

export const toDisplay = (kg: number, units: Units) => (units === "imperial" ? kg / KG_PER_LB : kg);
export const fromDisplay = (value: number, units: Units) =>
  units === "imperial" ? value * KG_PER_LB : value;

// Float slack so 72.0 / 0.5 = 143.99999 still counts as on the grid.
const EPS = 1e-9;
const tidy = (n: number) => Math.round(n * 1e6) / 1e6;

export interface SliderBand {
  kind: "recommended" | "milestone";
  fromPct: number;
  toPct: number;
}

export interface SliderModel {
  min: number;
  max: number;
  step: number;
  defaultValue: number;
  bands: SliderBand[];
}

/** Round to the step and clamp to [min, max]. */
export function snap(value: number, model: Pick<SliderModel, "min" | "max" | "step">): number {
  const onGrid = tidy(Math.round(value / model.step) * model.step);
  return Math.min(Math.max(onGrid, model.min), model.max);
}

/**
 * The slider in display units. Bounds are rounded inward to the step grid, so the slider never
 * offers a value outside the engine's bounds; bands are clipped to the slider.
 */
export function sliderModel(
  bounds: TargetBounds,
  recommended: Band | null | undefined,
  milestone: Band | null | undefined,
  units: Units,
): SliderModel {
  const step = units === "imperial" ? LB_STEP : bounds.step_kg;
  const min = tidy(Math.ceil(toDisplay(bounds.min_kg, units) / step - EPS) * step);
  const max = tidy(Math.floor(toDisplay(bounds.max_kg, units) / step + EPS) * step);
  const pct = (kg: number) => {
    const v = Math.min(Math.max(toDisplay(kg, units), min), max);
    return max > min ? ((v - min) / (max - min)) * 100 : 0;
  };
  const bands: SliderBand[] = [];
  const add = (kind: SliderBand["kind"], band: Band | null | undefined) => {
    if (!band) return;
    const fromPct = pct(band.min_kg);
    const toPct = pct(band.max_kg);
    if (toPct > fromPct) bands.push({ kind, fromPct, toPct });
  };
  add("recommended", recommended);
  add("milestone", milestone);
  return {
    min,
    max,
    step,
    defaultValue: snap(toDisplay(bounds.default_kg, units), { min, max, step }),
    bands,
  };
}

/** Whether a display-unit value sits inside the recommended band. */
export function inBand(value: number, band: Band | null | undefined, units: Units): boolean {
  if (!band) return false;
  const kg = fromDisplay(value, units);
  return kg >= band.min_kg - EPS && kg <= band.max_kg + EPS;
}
