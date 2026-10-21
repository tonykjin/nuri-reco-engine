// Onboarding answers -> PlanRequest (spec §11.3, "Captures -> PlanRequest field").
// This is the only place the demo's answers meet the engine's request (invariant 9). It only maps
// fields: option ids to engine ids, units to metric, birth date to age, rank to priority. Every
// nutrition decision stays in the engine.

import type { components } from "@/lib/api/schema";

import {
  type Activity,
  type Answers,
  type EatingStyle,
  EVENT_GOALS,
  type GoalDetail,
  type GoalType,
  rankedGoalTypes,
  WEIGHT_GOALS,
} from "./answers";

export type PlanRequest = components["schemas"]["PlanRequest"];

const KG_PER_LB = 0.45359237;
const CM_PER_INCH = 2.54;

const ACTIVITY: Record<Activity, string> = {
  mostly_sitting: "sedentary",
  some_walking: "light",
  on_feet_often: "moderate",
  on_feet_all_day: "active",
};

const DIETS: Partial<Record<EatingStyle, string>> = {
  vegetarian: "vegetarian",
  vegan: "vegan",
  pescatarian: "pescatarian",
};

const PATTERNS: Partial<Record<EatingStyle, string>> = {
  high_protein: "high_protein",
  mediterranean: "mediterranean",
  lower_carb: "low_carb_keto",
};

/** Whole years from birthDate to asOf (both YYYY-MM-DD). */
export function ageOn(birthDate: string, asOf: string): number {
  const [by, bm, bd] = birthDate.split("-").map(Number);
  const [y, m, d] = asOf.split("-").map(Number);
  const hadBirthday = m > bm || (m === bm && d >= bd);
  return y - by - (hadBirthday ? 0 : 1);
}

const round = (value: number, places: number) => {
  const f = 10 ** places;
  return Math.round(value * f) / f;
};

/** kg, rounded to 0.1 kg when converted from lb. */
export function toKg(weight: number, units: Answers["units"]): number {
  return units === "imperial" ? round(weight * KG_PER_LB, 1) : weight;
}

/** cm, rounded to whole cm when converted from ft/in. */
export function heightCm(answers: Pick<Answers, "units" | "heightCm" | "heightFt" | "heightIn">) {
  if (answers.units === "metric") return required(answers.heightCm, "height");
  const inches = required(answers.heightFt, "height (ft)") * 12 + (answers.heightIn ?? 0);
  return Math.round(inches * CM_PER_INCH);
}

/** SCOFF count of yes answers; null if any item is unanswered or declined. */
export function scoffScore(items: (boolean | null)[]): number | null {
  return items.some((i) => i === null) ? null : items.filter(Boolean).length;
}

function required<T>(value: T | null | undefined, name: string): T {
  if (value === null || value === undefined) throw new Error(`missing answer: ${name}`);
  return value;
}

/** The event name: the occasion for a deadline, the distance for a race, else the event type. */
export function eventName(type: GoalType, detail: GoalDetail): string | null {
  if (type === "deadline_event") return detail.event ?? null;
  if (type !== "endurance_event") return null;
  return (detail.eventType === "running" ? detail.distance : null) ?? detail.eventType ?? null;
}

function goal(type: GoalType, priority: number, answers: Answers) {
  const detail = answers.goalDetails[type] ?? {};
  const target = WEIGHT_GOALS.includes(type) ? (detail.targetWeight ?? null) : null;
  const isEvent = EVENT_GOALS.includes(type);
  return {
    type,
    priority,
    target_weight_kg: target === null ? null : toKg(target, answers.units),
    event: eventName(type, detail),
    event_date: isEvent ? (detail.eventDate ?? null) : null,
    rate_pct_bw_week: WEIGHT_GOALS.includes(type) ? answers.pace : null,
  };
}

export function mapAnswers(answers: Answers, { asOf }: { asOf: string }): PlanRequest {
  const { training, health } = answers;
  const types = rankedGoalTypes(answers);
  if (types.length === 0) throw new Error("missing answer: goals");
  return {
    profile: {
      age: ageOn(required(answers.birthDate, "birth date"), asOf),
      sex: required(answers.sex, "sex"),
      height_cm: heightCm(answers),
      weight_kg: toKg(required(answers.weight, "weight"), answers.units),
      body_fat_pct: answers.bodyFatPct,
      activity: ACTIVITY[required(answers.activity, "activity")],
      training: {
        resistance: training.type === "lifting" || training.type === "mixed",
        weekly_schedule: training.schedule,
        experience: training.experience,
      },
      flags: {
        pregnant: health.pregnancy === "pregnant",
        breastfeeding: health.pregnancy === "breastfeeding",
        ckd_stage: health.ckdStage,
        medications: health.medications,
        conditions: health.conditions,
        scoff_score: health.scoffDeclined ? null : scoffScore(health.scoff),
        ed_history: false,
        reported_symptoms: [],
      },
    },
    goals: types.map((type, i) => goal(type, i + 1, answers)),
    constraints: {
      allergens: answers.allergens,
      diet: DIETS[answers.eatingStyle] ?? null,
      religious: answers.religious,
      celiac: false,
    },
    preferences: {
      taste: answers.taste,
      dislikes: answers.dislikes,
      cook_time_min: answers.cookTimeMin,
      budget: answers.budget,
      cuisines: answers.cuisines,
      pattern_pref: PATTERNS[answers.eatingStyle] ?? null,
    },
    as_of: asOf,
    sequence_confirmed: answers.sequenceConfirmed ?? false,
  };
}
