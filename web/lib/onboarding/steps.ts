// The onboarding screens in order (spec §11.3, screens 1-13; results live at /results).
// A step whose condition is false is skipped.

import type { ComponentType } from "react";

import * as screens from "@/components/onboarding/screens";

import { type Answers, EVENT_GOALS, goalTypes, rankedGoalTypes, WEIGHT_GOALS } from "./answers";
import * as valid from "./validation";

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
  {
    id: "welcome",
    title: "Welcome to Nuri",
    condition: always,
    component: screens.Welcome,
    complete: valid.welcomeComplete,
  },
  {
    id: "goals",
    title: "What are your goals?",
    condition: always,
    component: screens.Goals,
    complete: valid.goalsComplete,
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
    complete: (a) => valid.goalDetailsComplete(a),
  },
  {
    id: "about",
    title: "About you",
    condition: always,
    component: screens.About,
    complete: (a) => valid.aboutComplete(a),
  },
  {
    id: "activity",
    title: "Daily activity outside workouts",
    condition: always,
    component: screens.Activity,
    complete: valid.activityComplete,
  },
  {
    id: "training",
    title: "How do you train?",
    condition: always,
    component: screens.Training,
    complete: valid.trainingComplete,
  },
  {
    id: "health",
    title: "Health check",
    condition: always,
    component: screens.Health,
    complete: valid.healthComplete,
  },
  {
    id: "eating",
    title: "How do you like to eat?",
    condition: always,
    component: screens.Eating,
  },
  {
    id: "avoid",
    title: "Allergies and foods you avoid",
    condition: always,
    component: screens.Avoid,
  },
  {
    id: "taste",
    title: "Taste quick-check",
    condition: always,
    component: screens.Taste,
  },
  {
    id: "pace",
    title: "Pick your pace",
    // The engine applies a chosen rate to deficits only, so gain goals keep its default pace.
    condition: (a) => hasAny(a, ["lose_fat"]),
    component: screens.Pace,
  },
  {
    id: "building",
    title: "Building your plan…",
    condition: always,
    component: screens.Building,
  },
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
