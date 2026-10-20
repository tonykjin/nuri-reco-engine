// The onboarding screens in order (spec §11.3). A step whose condition is false is skipped.

import type { ComponentType } from "react";

import * as screens from "@/components/onboarding/screens";

import {
  type Answers,
  EVENT_GOALS,
  goalTypes,
  rankedGoalTypes,
  WEIGHT_GOALS,
} from "./answers";

export interface Step {
  id: string;
  title: string;
  condition: (answers: Answers) => boolean;
  component: ComponentType;
  /** Continue stays disabled until this holds (default: always). */
  complete?: (answers: Answers) => boolean;
}

const always = () => true;
const hasAny = (answers: Answers, types: string[]) =>
  goalTypes(answers.goals).some((t) => types.includes(t));

export const STEPS: Step[] = [
  { id: "welcome", title: "Welcome", condition: always, component: screens.Welcome },
  {
    id: "goals",
    title: "What are your goals?",
    condition: always,
    component: screens.Goals,
    complete: (a) => a.goals.length > 0,
  },
  {
    id: "priority",
    title: "Which matters most?",
    condition: (a) => rankedGoalTypes(a).length > 1,
    component: screens.Priority,
  },
  {
    id: "goal-details",
    title: "Goal details",
    condition: (a) => hasAny(a, [...WEIGHT_GOALS, ...EVENT_GOALS]),
    component: screens.GoalDetails,
  },
  { id: "about", title: "About you", condition: always, component: screens.About },
  {
    id: "activity",
    title: "Daily activity outside workouts",
    condition: always,
    component: screens.Activity,
  },
  { id: "training", title: "Training", condition: always, component: screens.Training },
  { id: "health", title: "Health check", condition: always, component: screens.Health },
  { id: "eating", title: "How do you like to eat?", condition: always, component: screens.Eating },
  {
    id: "avoid",
    title: "Allergies and foods you avoid",
    condition: always,
    component: screens.Avoid,
  },
  { id: "taste", title: "Taste quick-check", condition: always, component: screens.Taste },
  {
    id: "pace",
    title: "Pick your pace",
    condition: (a) => hasAny(a, WEIGHT_GOALS),
    component: screens.Pace,
  },
  { id: "building", title: "Building your plan", condition: always, component: screens.Building },
  { id: "results", title: "Your plan", condition: always, component: screens.Results },
];

export const STEP_IDS = STEPS.map((s) => s.id);

export function stepById(id: string): Step | undefined {
  return STEPS.find((s) => s.id === id);
}

export function visibleSteps(answers: Answers): Step[] {
  return STEPS.filter((s) => s.condition(answers));
}

/** The next step after `id` whose condition holds. */
export function nextStep(id: string, answers: Answers): Step | undefined {
  return STEPS.slice(STEP_IDS.indexOf(id) + 1).find((s) => s.condition(answers));
}

/** The previous step before `id` whose condition holds. */
export function previousStep(id: string, answers: Answers): Step | undefined {
  return STEPS.slice(0, STEP_IDS.indexOf(id))
    .reverse()
    .find((s) => s.condition(answers));
}
