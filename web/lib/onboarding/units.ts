// Switching metric <-> imperial converts what's already entered, so nothing has to be retyped.

import type { Answers, GoalDetail } from "./answers";

export const KG_PER_LB = 0.45359237;
const CM_PER_INCH = 2.54;

const round1 = (n: number) => Math.round(n * 10) / 10;

function weight(value: number | null | undefined, to: Answers["units"]): number | null {
  if (value === null || value === undefined) return null;
  return round1(to === "imperial" ? value / KG_PER_LB : value * KG_PER_LB);
}

export function switchUnits(answers: Answers, to: Answers["units"]): Partial<Answers> {
  if (answers.units === to) return {};
  const goalDetails = Object.fromEntries(
    Object.entries(answers.goalDetails).map(([type, d]) => [
      type,
      d?.targetWeight == null ? d : { ...d, targetWeight: weight(d.targetWeight, to) },
    ]),
  ) as Partial<Record<keyof Answers["goalDetails"], GoalDetail>>;
  const height =
    to === "imperial"
      ? (() => {
          if (answers.heightCm === null) return { heightFt: null, heightIn: null };
          const inches = Math.round(answers.heightCm / CM_PER_INCH);
          return { heightFt: Math.floor(inches / 12), heightIn: inches % 12 };
        })()
      : {
          heightCm:
            answers.heightFt === null
              ? null
              : Math.round((answers.heightFt * 12 + (answers.heightIn ?? 0)) * CM_PER_INCH),
        };
  return {
    units: to,
    weight: weight(answers.weight, to),
    goalDetails,
    ...height,
  };
}
