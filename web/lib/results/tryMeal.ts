// Try a meal: GET /v1/knowledge/foods for the picker, POST /v1/score/evaluate for the score. The
// engine holds the nutrient data and the formulas; this file only fetches and labels.

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { PlanRequest } from "@/lib/onboarding/mapAnswers";

import { COMPONENT_LABELS, MICRO_LABELS, title } from "./format";

export type FoodListing = components["schemas"]["FoodListing"];
export type ScoreEvaluation = components["schemas"]["ScoreEvaluation"];
export type ComponentScore = components["schemas"]["ComponentScore"];
type DayType = components["schemas"]["ScoreEvaluateRequest"]["day_type"];

export const MIN_FOODS = 2;
export const MAX_FOODS = 4;

export interface MealRow {
  key: string | null;
  grams: number | null;
}

// A starting meal so the card shows something useful straight away.
export const STARTER_MEAL: MealRow[] = [
  { key: "chicken_breast_roasted", grams: 150 },
  { key: "rice_white_cooked", grams: 200 },
  { key: "broccoli_boiled", grams: 100 },
];

function message(error: unknown, fallback: string): string {
  return (error as { error?: { message?: string } } | undefined)?.error?.message ?? fallback;
}

export async function fetchFoods(signal?: AbortSignal): Promise<FoodListing[]> {
  const { data, error } = await api.GET("/v1/knowledge/foods", { signal });
  if (error || !data) throw new Error(message(error, "The food list didn't load."));
  return data;
}

/** The meal's score; null when the plan has no score profile (blocked). */
export async function evaluateMeal(
  request: PlanRequest,
  rows: MealRow[],
  dayType: string,
  phase: string,
  signal?: AbortSignal,
): Promise<ScoreEvaluation | null> {
  const { data, error } = await api.POST("/v1/score/evaluate", {
    body: {
      request,
      items: readyItems(rows),
      level: "meal",
      day_type: dayType as DayType,
      phase,
    },
    signal,
  });
  if (error || !data) throw new Error(message(error, "The score service didn't respond."));
  return data.evaluation ?? null;
}

/** Rows with a food and positive grams, as API items. */
export function readyItems(rows: MealRow[]): { key: string; grams: number }[] {
  return rows.flatMap((r) =>
    r.key && r.grams && r.grams > 0 ? [{ key: r.key, grams: r.grams }] : [],
  );
}

/** 2-4 foods, each picked once, each with grams. */
export function canScore(rows: MealRow[]): boolean {
  const items = readyItems(rows);
  const keys = new Set(items.map((i) => i.key));
  return (
    items.length === rows.length &&
    keys.size === items.length &&
    items.length >= MIN_FOODS &&
    items.length <= MAX_FOODS
  );
}

export function componentLabel(id: string): string {
  return COMPONENT_LABELS[id] ?? MICRO_LABELS[id] ?? title(id);
}

export const LEFT_OUT_REASONS: Record<string, string> = {
  not_at_meal_level: "not scored for a single meal",
  disabled: "set by your dietitian",
};
