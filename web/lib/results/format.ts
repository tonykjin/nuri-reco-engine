// Display helpers for the results screen. They label and format engine values; they never
// derive, compare or adjust them (invariant 9: no nutrition logic in the web app).

import type { components } from "@/lib/api/schema";

export type PlanResponse = components["schemas"]["PlanResponse"];
export type Phase = components["schemas"]["Phase"];
export type PhaseScoreProfile = components["schemas"]["PhaseScoreProfile"];
export type ScoreComponent = components["schemas"]["ScoreComponent"];
export type ScoreTarget = components["schemas"]["ScoreTarget"];
export type MicronutrientTarget = components["schemas"]["MicronutrientTarget"];

const LB_PER_KG = 1 / 0.45359237;

export const whole = (n: number) => Math.round(n).toLocaleString("en-US");

/** A number as the engine gave it, to at most `places` decimals. */
export const num = (n: number, places = 1) =>
  Number(n.toFixed(places)).toLocaleString("en-US", { maximumFractionDigits: places });

export function weight(kg: number, units: "metric" | "imperial"): string {
  return units === "imperial" ? `${num(kg * LB_PER_KG)} lb` : `${num(kg)} kg`;
}

export function date(iso: string | null | undefined): string {
  if (!iso) return "";
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function dateRange(start?: string | null, end?: string | null): string {
  if (start && end) return `${date(start)} – ${date(end)}`;
  if (start) return `from ${date(start)}`;
  return end ? `until ${date(end)}` : "";
}

export const title = (id: string) => id.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());

const UNITS: Record<string, string> = { mcg_dfe: "mcg DFE" };
export const unit = (u: string) => UNITS[u] ?? u;

/** "112–154 g", "at least 26 g", "at most 2,300 mg"; whole numbers unless the unit is small. */
export function target(t: ScoreTarget): string {
  const u = unit(t.unit);
  const v = (n: number) => (n < 10 ? num(n) : whole(n));
  if (t.low != null && t.high != null) return `${v(t.low)}–${v(t.high)} ${u}`;
  if (t.min != null && t.max != null) return `${v(t.min)}–${v(t.max)} ${u}`;
  if (t.min != null) return `at least ${v(t.min)} ${u}`;
  if (t.max != null) return `at most ${v(t.max)} ${u}`;
  return "";
}

export const WEIGHT_LABELS: Record<string, string> = {
  energy: "Energy balance",
  protein: "Protein",
  carb: "Carbs for your day",
  fiber: "Fiber",
  micro: "Vitamins and minerals",
  pattern: "Eating pattern",
  moderation: "Moderation",
};

export const COMPONENT_LABELS: Record<string, string> = {
  energy: "Calories",
  protein: "Protein",
  carb: "Carbs",
  fiber: "Fiber",
  sat_fat: "Saturated fat",
  free_sugar: "Free sugars",
  sodium: "Sodium",
  produce: "Fruit and vegetables",
};

export const MICRO_LABELS: Record<string, string> = {
  vitamin_b12: "Vitamin B12",
  vitamin_d: "Vitamin D",
};

export const DISABLED_LABELS: Record<string, string> = {
  carb_auto_target: "Carb target (set by your dietitian)",
};

export const DISABLED_REASONS: Record<string, string> = {
  rd_set: "handled by your dietitian",
};

/** Referral targets (guardrails.yaml referral_to). */
export const REFERRAL_LABELS: Record<string, string> = {
  rd: "a registered dietitian",
  sports_rd: "a sports dietitian",
  doctor: "your doctor",
  clinician: "your doctor",
  family: "a parent or guardian",
};

/** "Talk to a parent or guardian or your doctor"; resources-only referrals get their own title. */
export function referralTitle(to: string[]): string {
  const people = [
    ...new Set(to.filter((t) => t !== "resources").map((t) => REFERRAL_LABELS[t] ?? title(t))),
  ];
  return people.length ? `Talk to ${people.join(" or ")}` : "Where to find support";
}

export const ENERGY_LABELS: Record<string, string> = {
  deficit: "Calorie deficit",
  maintenance: "Maintenance",
  surplus: "Calorie surplus",
};

/** Day types in week order of effort, for tabs. */
export const DAY_ORDER = ["rest", "easy", "quality", "long", "carb_load"];
export const byDayOrder = (a: string, b: string) =>
  (DAY_ORDER.indexOf(a) + 1 || 99) - (DAY_ORDER.indexOf(b) + 1 || 99);

export const DAY_LABELS: Record<string, string> = {
  rest: "Rest",
  easy: "Easy",
  quality: "Hard",
  long: "Long",
  carb_load: "Carb load",
};

export const APPLIES_LABELS: Record<string, string> = {
  meal: "Meal",
  day: "Day",
  week: "Week",
};

/** Every rule id the response cites, in order of first appearance (for the dev drawer). */
export function ruleIds(value: unknown): string[] {
  const found = new Set<string>();
  const walk = (node: unknown) => {
    if (Array.isArray(node)) node.forEach(walk);
    else if (node && typeof node === "object") {
      for (const [key, v] of Object.entries(node)) {
        if ((key === "rule_ids" || key === "weight_rule_ids") && Array.isArray(v)) {
          v.forEach((id) => found.add(String(id)));
        } else if (key === "rule_id" && typeof v === "string") found.add(v);
        else walk(v);
      }
    }
  };
  walk(value);
  return [...found];
}
