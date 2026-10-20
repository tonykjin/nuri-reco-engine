// Answer fixtures for the golden personas (spec §11.2): demo prefill and mapAnswers tests.

import type { Answers } from "../answers";
import glp1T2dStrength from "./glp1_t2d_strength.json";
import goalBmiLow from "./goal_bmi_low.json";
import hybrid from "./hybrid.json";
import marathonFatloss from "./marathon_fatloss.json";
import maya from "./maya.json";
import noviceRecomp from "./novice_recomp.json";
import pregnant from "./pregnant.json";
import under18 from "./under18.json";
import veganMuscle from "./vegan_muscle.json";
import wedding8wk from "./wedding_8wk.json";

export interface PersonaFixture {
  as_of: string;
  answers: Answers;
}

export const PERSONAS = {
  maya,
  novice_recomp: noviceRecomp,
  marathon_fatloss: marathonFatloss,
  wedding_8wk: wedding8wk,
  hybrid,
  glp1_t2d_strength: glp1T2dStrength,
  vegan_muscle: veganMuscle,
  under18,
  pregnant,
  goal_bmi_low: goalBmiLow,
} as unknown as Record<string, PersonaFixture>;
