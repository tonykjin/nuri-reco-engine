// What to eat: PlanResponse.patterns, and POST /v1/recommendations/foods for the filtered list.
// The engine ranks and explains; this file only builds the context and labels the options.

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { PlanRequest } from "@/lib/onboarding/mapAnswers";

export type FoodContext = components["schemas"]["FoodContext"];
export type FoodRecommendation = components["schemas"]["FoodRecommendation"];
export type PatternRecommendation = components["schemas"]["PatternRecommendation"];
export type PantryItem = components["schemas"]["PantryItem"];
export type MealSlot = FoodContext["meal_slot"];
export type DayType = FoodContext["day_type"];
export type Ripeness = NonNullable<PantryItem["ripeness"]>;

// Long enough that a pantry boost from outside the top 10 is visible.
export const LIST_LENGTH = 30;

export async function fetchRankedFoods(
  request: PlanRequest,
  context: FoodContext,
  signal?: AbortSignal,
): Promise<FoodRecommendation[]> {
  const { data, error } = await api.POST("/v1/recommendations/foods", {
    body: { request, context, limit: LIST_LENGTH },
    signal,
  });
  if (error || !data) {
    const message = (error as { error?: { message?: string } } | undefined)?.error?.message;
    throw new Error(message ?? "The food service didn't respond.");
  }
  return data.foods;
}

export function foodContext(
  mealSlot: MealSlot,
  dayType: string,
  phase: string,
  pantry: PantryItem[],
): FoodContext {
  return { meal_slot: mealSlot, day_type: dayType as DayType, phase, pantry };
}

/** The pantry with this food added or updated (one entry per food). */
export function upsertPantry(pantry: PantryItem[], item: PantryItem): PantryItem[] {
  const i = pantry.findIndex((p) => p.key === item.key);
  return i < 0 ? [...pantry, item] : pantry.map((p, j) => (j === i ? item : p));
}

export const MEAL_SLOT_LABELS: Record<MealSlot, string> = {
  any: "Any meal",
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snack",
  pre_race: "Before a session",
  during: "During a session",
  recovery: "Recovery",
};

export const RIPENESS_LABELS: Record<Ripeness, string> = {
  unripe: "Unripe",
  ripe: "Ripe",
  peak: "Peak",
  overripe: "Overripe",
};
