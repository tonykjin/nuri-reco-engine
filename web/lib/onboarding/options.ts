// Option lists for the onboarding screens: ids the mapper understands, plus short labels.

import type {
  Activity,
  DayType,
  EatingStyle,
  Experience,
  Pregnancy,
  TrainingType,
} from "./answers";

export interface Option<T extends string> {
  id: T;
  label: string;
  hint?: string;
}

export const ACTIVITY_OPTIONS: Option<Activity>[] = [
  {
    id: "mostly_sitting",
    label: "Mostly sitting",
    hint: "Desk job, little walking",
  },
  {
    id: "some_walking",
    label: "Some walking",
    hint: "On your feet now and then",
  },
  {
    id: "on_feet_often",
    label: "On your feet a lot",
    hint: "Teacher, retail, lots of errands",
  },
  {
    id: "on_feet_all_day",
    label: "On your feet all day",
    hint: "Manual or very active work",
  },
];

export const TRAINING_TYPES: Option<TrainingType>[] = [
  { id: "none", label: "I don't train right now" },
  { id: "lifting", label: "Lifting" },
  { id: "running", label: "Running or cardio" },
  { id: "mixed", label: "A mix of both" },
];

export const EXPERIENCE_OPTIONS: Option<Experience>[] = [
  { id: "novice", label: "Under a year" },
  { id: "intermediate", label: "1-3 years" },
  { id: "advanced", label: "3+ years" },
  { id: "returning", label: "Coming back after a break" },
];

/** The 7-day strip cycles through these on each tap. */
export const DAY_CYCLE: DayType[] = ["rest", "easy", "quality", "long"];
export const DAY_LABELS: Partial<Record<DayType, string>> = {
  rest: "Rest",
  easy: "Easy",
  quality: "Hard",
  long: "Long",
};
export const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function nextDayType(day: DayType): DayType {
  const i = DAY_CYCLE.indexOf(day);
  return DAY_CYCLE[(i + 1) % DAY_CYCLE.length];
}

export const OCCASIONS: Option<string>[] = [
  { id: "wedding", label: "Wedding" },
  { id: "holiday", label: "Holiday" },
  { id: "other", label: "Something else" },
];

export const EVENT_TYPES: Option<string>[] = [
  { id: "running", label: "Running race" },
  { id: "cycling", label: "Cycling" },
  { id: "triathlon", label: "Triathlon" },
  { id: "other", label: "Something else" },
];

export const DISTANCES: Option<string>[] = [
  { id: "5k", label: "5K" },
  { id: "10k", label: "10K" },
  { id: "half_marathon", label: "Half marathon" },
  { id: "marathon", label: "Marathon" },
  { id: "ultra", label: "Ultra" },
];

export const PREGNANCY_OPTIONS: Option<Pregnancy>[] = [
  { id: "no", label: "No" },
  { id: "pregnant", label: "I'm pregnant" },
  { id: "breastfeeding", label: "I'm breastfeeding" },
  { id: "prefer_not_to_say", label: "Prefer not to say" },
];

/** Engine condition ids (guardrails.yaml). Kidney disease is asked separately, with a stage. */
export const CONDITIONS: Option<string>[] = [
  { id: "t2d", label: "Type 2 diabetes" },
  { id: "hypertension", label: "High blood pressure" },
];

/** Engine medication ids (guardrails.yaml). */
export const MEDICATIONS: Option<string>[] = [
  { id: "glp1_agonist", label: "GLP-1 (e.g. Ozempic, Wegovy, Mounjaro)" },
  { id: "metformin", label: "Metformin" },
  { id: "sglt2_inhibitor", label: "SGLT2 inhibitor (e.g. Jardiance, Farxiga)" },
  { id: "insulin", label: "Insulin" },
  { id: "sulfonylurea", label: "Sulfonylurea (e.g. gliclazide)" },
  { id: "warfarin", label: "Warfarin" },
  { id: "antihypertensive", label: "Blood pressure medication" },
];

// TODO(RD-review): SCOFF wording, softened from Morgan et al. (1999).
export const SCOFF_ITEMS = [
  "Do you make yourself sick because you feel uncomfortably full?",
  "Do you worry you've lost control over how much you eat?",
  "Have you lost more than 6 kg (14 lb) in the last 3 months?",
  "Do you believe you're fat when others say you're too thin?",
  "Would you say food dominates your life?",
];

export const EATING_STYLES: Option<EatingStyle>[] = [
  { id: "no_preference", label: "No preference" },
  { id: "balanced", label: "Balanced" },
  { id: "high_protein", label: "High-protein" },
  { id: "mediterranean", label: "Mediterranean" },
  { id: "lower_carb", label: "Lower-carb" },
  { id: "vegetarian", label: "Vegetarian" },
  { id: "vegan", label: "Vegan" },
  { id: "pescatarian", label: "Pescatarian" },
];

/** Top-9 allergens, as words the engine's allergen vocabulary understands (constraints.yaml). */
export const ALLERGENS: Option<string>[] = [
  { id: "milk", label: "Milk" },
  { id: "egg", label: "Egg" },
  { id: "fish", label: "Fish" },
  { id: "shellfish", label: "Shellfish" },
  { id: "tree nuts", label: "Tree nuts" },
  { id: "peanuts", label: "Peanuts" },
  { id: "wheat", label: "Wheat" },
  { id: "soy", label: "Soy" },
  { id: "sesame", label: "Sesame" },
];

export const RELIGIOUS: Option<string>[] = [
  { id: "halal", label: "Halal" },
  { id: "kosher", label: "Kosher" },
  { id: "hindu_vegetarian", label: "Hindu vegetarian" },
  { id: "jain", label: "Jain" },
];

/** PRD taste dimensions; only the ones the user moves are sent. */
export const TASTE_DIMENSIONS: (Option<string> & {
  low: string;
  high: string;
})[] = [
  { id: "sweetness", label: "Sweetness", low: "Not sweet", high: "Love sweet" },
  { id: "richness", label: "Richness", low: "Light", high: "Rich" },
  { id: "umami", label: "Savoury (umami)", low: "Mild", high: "Very savoury" },
  {
    id: "bitterness",
    label: "Bitterness",
    low: "Avoid bitter",
    high: "Love bitter",
  },
  { id: "texture", label: "Texture", low: "Soft", high: "Crunchy" },
];

export const CUISINES: Option<string>[] = [
  { id: "mediterranean", label: "Mediterranean" },
  { id: "japanese", label: "Japanese" },
  { id: "italian", label: "Italian" },
  { id: "mexican", label: "Mexican" },
  { id: "indian", label: "Indian" },
  { id: "chinese", label: "Chinese" },
  { id: "thai", label: "Thai" },
  { id: "middle_eastern", label: "Middle Eastern" },
];

export const COOK_TIMES = [15, 30, 45, 60];

export const BUDGETS: Option<"low" | "medium" | "high">[] = [
  { id: "low", label: "Tight" },
  { id: "medium", label: "Medium" },
  { id: "high", label: "Flexible" },
];

/** Pace slider bounds (% body weight per week). Display only: the engine applies the real cap. */
export const PACE = { min: 0.25, max: 1, step: 0.05 };
