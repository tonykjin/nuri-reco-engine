// What the onboarding screens collect, in the user's own terms (units as entered, birth date not
// age, option ids not engine ids). mapAnswers.ts turns this into a PlanRequest.

export type Units = "metric" | "imperial";

export type DayType = "rest" | "easy" | "quality" | "long" | "carb_load";

/** Screen 2 options. Some map to more than one engine goal type (see GOAL_CHOICES). */
export type GoalChoice =
  | "lose_fat"
  | "build_muscle"
  | "both"
  | "gain_weight"
  | "event"
  | "date"
  | "strength"
  | "eat_healthier"
  | "blood_sugar"
  | "heart_health"
  | "glp1";

/** Engine goal types (Matrix A ids) the screens can produce. */
export type GoalType =
  | "lose_fat"
  | "build_muscle"
  | "gain_weight"
  | "endurance_event"
  | "deadline_event"
  | "strength_hybrid"
  | "maintain"
  | "t2d"
  | "hypertension"
  | "glp1";

export type Activity = "mostly_sitting" | "some_walking" | "on_feet_often" | "on_feet_all_day";
export type TrainingType = "none" | "lifting" | "running" | "mixed";
export type Experience = "novice" | "intermediate" | "advanced" | "returning";
export type Pregnancy = "no" | "pregnant" | "breastfeeding" | "prefer_not_to_say";
export type EatingStyle =
  | "no_preference"
  | "balanced"
  | "high_protein"
  | "mediterranean"
  | "lower_carb"
  | "vegetarian"
  | "vegan"
  | "pescatarian";

export interface GoalDetail {
  /** In the user's units (kg or lb). */
  targetWeight?: number | null;
  /** Deadline goals: the occasion (wedding, holiday, other). */
  event?: string | null;
  /** Endurance goals: running, cycling, triathlon or other; running also has a distance. */
  eventType?: string | null;
  distance?: string | null;
  /** YYYY-MM-DD */
  eventDate?: string | null;
}

export interface Answers {
  firstName: string;
  goals: GoalChoice[];
  /** Goal types in the order the user ranked them; empty until screen 3 is answered. */
  ranking: GoalType[];
  /** The user confirmed the order after the engine asked (needs_ordering). */
  sequenceConfirmed?: boolean;
  goalDetails: Partial<Record<GoalType, GoalDetail>>;
  units: Units;
  sex: "female" | "male" | null;
  /** YYYY-MM-DD */
  birthDate: string | null;
  /** kg or lb, per `units`. */
  weight: number | null;
  heightCm: number | null;
  heightFt: number | null;
  heightIn: number | null;
  /** null = skipped ("skip if unsure"). */
  bodyFatPct: number | null;
  activity: Activity | null;
  training: {
    type: TrainingType;
    daysPerWeek: number;
    schedule: DayType[];
    experience: Experience | null;
  };
  health: {
    pregnancy: Pregnancy;
    ckdStage: number | null;
    medications: string[];
    conditions: string[];
    /** The five SCOFF yes/no items; null = not answered. */
    scoff: (boolean | null)[];
    /** "Prefer not to say" for the SCOFF items. */
    scoffDeclined?: boolean;
  };
  eatingStyle: EatingStyle;
  /** Meals and snacks on a usual day; null = not answered (the engine uses its default). */
  mealsPerDay: number | null;
  snacksPerDay: number | null;
  allergens: string[];
  religious: string[];
  dislikes: string[];
  /** Only the taste sliders the user moved (skip = neutral). */
  taste: Record<string, number>;
  cuisines: string[];
  cookTimeMin: number | null;
  budget: "low" | "medium" | "high" | null;
  /** Chosen weekly rate, % of body weight; null = engine default. */
  pace: number | null;
}

export const initialAnswers: Answers = {
  firstName: "",
  goals: [],
  ranking: [],
  sequenceConfirmed: false,
  goalDetails: {},
  units: "metric",
  sex: null,
  birthDate: null,
  weight: null,
  heightCm: null,
  heightFt: null,
  heightIn: null,
  bodyFatPct: null,
  activity: null,
  training: {
    type: "none",
    daysPerWeek: 0,
    schedule: ["rest", "rest", "rest", "rest", "rest", "rest", "rest"],
    experience: null,
  },
  health: {
    pregnancy: "no",
    ckdStage: null,
    medications: [],
    conditions: [],
    scoff: [null, null, null, null, null],
    scoffDeclined: false,
  },
  eatingStyle: "no_preference",
  mealsPerDay: null,
  snacksPerDay: null,
  allergens: [],
  religious: [],
  dislikes: [],
  taste: {},
  cuisines: [],
  cookTimeMin: null,
  budget: null,
  pace: null,
};

// --- Options (screen copy) ---

export const GOAL_CHOICES: {
  id: GoalChoice;
  label: string;
  types: GoalType[];
}[] = [
  { id: "lose_fat", label: "Lose fat", types: ["lose_fat"] },
  { id: "build_muscle", label: "Build muscle", types: ["build_muscle"] },
  {
    id: "both",
    label: "Lose fat and build muscle",
    types: ["lose_fat", "build_muscle"],
  },
  { id: "gain_weight", label: "Gain weight", types: ["gain_weight"] },
  { id: "event", label: "Train for an event", types: ["endurance_event"] },
  {
    id: "date",
    label: "Feel ready for a date (wedding, holiday)",
    types: ["deadline_event"],
  },
  {
    id: "strength",
    label: "Get stronger and fitter",
    types: ["strength_hybrid"],
  },
  { id: "eat_healthier", label: "Eat healthier", types: ["maintain"] },
  { id: "blood_sugar", label: "Manage blood sugar", types: ["t2d"] },
  { id: "heart_health", label: "Heart health", types: ["hypertension"] },
  { id: "glp1", label: "I'm on a GLP-1", types: ["glp1"] },
];

export const MAX_GOALS = 3;

export const GOAL_LABELS: Record<GoalType, string> = {
  lose_fat: "Lose fat",
  build_muscle: "Build muscle",
  gain_weight: "Gain weight",
  endurance_event: "Train for an event",
  deadline_event: "Ready for a date",
  strength_hybrid: "Get stronger and fitter",
  maintain: "Eat healthier",
  t2d: "Manage blood sugar",
  hypertension: "Heart health",
  glp1: "GLP-1 support",
};

/** Engine goal types for the chosen options, in choice order, without duplicates. */
export function goalTypes(choices: GoalChoice[]): GoalType[] {
  const types = choices.flatMap((c) => GOAL_CHOICES.find((g) => g.id === c)?.types ?? []);
  return [...new Set(types)];
}

/** Goal types in priority order: the user's ranking, then any chosen goal it doesn't list. */
export function rankedGoalTypes(answers: Answers): GoalType[] {
  const chosen = goalTypes(answers.goals);
  const ranked = answers.ranking.filter((t) => chosen.includes(t));
  return [...ranked, ...chosen.filter((t) => !ranked.includes(t))];
}

export const WEIGHT_GOALS: GoalType[] = ["lose_fat", "gain_weight"];
export const EVENT_GOALS: GoalType[] = ["endurance_event", "deadline_event"];
