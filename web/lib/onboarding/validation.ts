// Continue is enabled only when a screen's answers are complete and well-formed.
// These checks are about input shape (a date in the past, a positive number), never nutrition.

import { type Answers, EVENT_GOALS, goalTypes, WEIGHT_GOALS } from "./answers";

const DATE = /^\d{4}-\d{2}-\d{2}$/;

export function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export const isDate = (value: string | null | undefined): value is string =>
  !!value && DATE.test(value) && !Number.isNaN(Date.parse(value));

const positive = (n: number | null | undefined) => typeof n === "number" && n > 0;

export function welcomeComplete(a: Answers): boolean {
  return a.firstName.trim().length > 0;
}

export function goalsComplete(a: Answers): boolean {
  return a.goals.length > 0;
}

export function goalDetailsComplete(a: Answers, asOf = today()): boolean {
  return goalTypes(a.goals).every((type) => {
    const d = a.goalDetails[type] ?? {};
    if (WEIGHT_GOALS.includes(type)) {
      return d.targetWeight === null || d.targetWeight === undefined || positive(d.targetWeight);
    }
    if (!EVENT_GOALS.includes(type)) return true;
    const dated = isDate(d.eventDate) && d.eventDate > asOf;
    if (type === "deadline_event") return dated && !!d.event;
    return dated && !!d.eventType && (d.eventType !== "running" || !!d.distance);
  });
}

export function aboutComplete(a: Answers, asOf = today()): boolean {
  const height =
    a.units === "metric"
      ? positive(a.heightCm)
      : positive(a.heightFt) && (a.heightIn ?? 0) >= 0 && (a.heightIn ?? 0) < 12;
  const bodyFat = a.bodyFatPct === null || (a.bodyFatPct > 2 && a.bodyFatPct < 70);
  return (
    a.sex !== null &&
    isDate(a.birthDate) &&
    a.birthDate < asOf &&
    positive(a.weight) &&
    height &&
    bodyFat
  );
}

export function activityComplete(a: Answers): boolean {
  return a.activity !== null;
}

export function trainingComplete(a: Answers): boolean {
  const days = a.training.daysPerWeek;
  return a.training.type === "none" || (days >= 1 && days <= 7);
}

export function healthComplete(a: Answers): boolean {
  const scoff = a.health.scoffDeclined || a.health.scoff.every((i) => i !== null);
  const ckd = a.health.ckdStage === null || (a.health.ckdStage >= 1 && a.health.ckdStage <= 5);
  return scoff && ckd;
}
