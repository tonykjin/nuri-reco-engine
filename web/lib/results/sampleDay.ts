// Sample day: POST /v1/recommendations/day. The engine picks the foods and portions; this file
// only fetches and labels them.

import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import type { PlanRequest } from "@/lib/onboarding/mapAnswers";

export type SampleDay = components["schemas"]["SampleDay"];
type DayType = components["schemas"]["DayRecommendationRequest"]["day_type"];

/** The sample day for a phase and day type; null when the plan has none (blocked). */
export async function fetchSampleDay(
  request: PlanRequest,
  dayType: string,
  phase: string,
  signal?: AbortSignal,
): Promise<SampleDay | null> {
  const { data, error } = await api.POST("/v1/recommendations/day", {
    body: { request, day_type: dayType as DayType, phase },
    signal,
  });
  if (error || !data) {
    const message = (error as { error?: { message?: string } } | undefined)?.error?.message;
    throw new Error(message ?? "The sample day service didn't respond.");
  }
  return data.day ?? null;
}

export const SLOT_LABELS: Record<string, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  extra_meal: "Extra meal",
  pre_session: "Before your session",
  dinner: "Dinner",
  snack: "Snack",
};

export const MACRO_LABELS: Record<string, string> = {
  kcal: "Calories",
  protein_g: "Protein",
  carb_g: "Carbs",
  fat_g: "Fat",
};

/** A signed percentage as the engine sent it, e.g. "+6.7%", "−3%", "on target". */
export function signedPct(pct: number): string {
  if (pct === 0) return "on target";
  const value = Math.abs(pct).toLocaleString("en-US", { maximumFractionDigits: 1 });
  return `${pct > 0 ? "+" : "−"}${value}%`;
}
