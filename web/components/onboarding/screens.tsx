"use client";

// Onboarding screens. Welcome, Goals and Priority work; the rest are placeholders that show what
// they capture until Task 19 builds them. Prefill a persona on Welcome to step through with data.

import { useMemo } from "react";

import {
  type Answers,
  GOAL_CHOICES,
  GOAL_LABELS,
  goalTypes,
  MAX_GOALS,
  rankedGoalTypes,
} from "@/lib/onboarding/answers";
import { mapAnswers } from "@/lib/onboarding/mapAnswers";
import { PERSONAS } from "@/lib/onboarding/personas";
import { useAnswers } from "@/lib/onboarding/store";

const chip = (selected: boolean) =>
  `rounded-full border px-4 py-2 text-sm transition ${
    selected ? "border-ink bg-ink text-white" : "border-ink/20 bg-white hover:border-ink/50"
  }`;

export function Welcome() {
  const firstName = useAnswers((s) => s.answers.firstName);
  const update = useAnswers((s) => s.update);
  const replace = useAnswers((s) => s.replace);
  return (
    <div className="space-y-6">
      <label className="block space-y-2">
        <span className="text-sm text-ink/70">What should we call you?</span>
        <input
          className="w-full rounded-lg border border-ink/20 bg-white px-3 py-2"
          value={firstName}
          onChange={(e) => update({ firstName: e.target.value })}
          placeholder="First name"
        />
      </label>
      <details className="text-sm">
        <summary className="cursor-pointer text-ink/70">Prefill as persona…</summary>
        <div className="mt-3 flex flex-wrap gap-2">
          {Object.entries(PERSONAS).map(([name, persona]) => (
            <button
              key={name}
              type="button"
              className={chip(false)}
              onClick={() => replace(persona.answers)}
            >
              {name.replaceAll("_", " ")}
            </button>
          ))}
        </div>
      </details>
    </div>
  );
}

export function Goals() {
  const goals = useAnswers((s) => s.answers.goals);
  const update = useAnswers((s) => s.update);
  const toggle = (id: Answers["goals"][number]) => {
    const next = goals.includes(id) ? goals.filter((g) => g !== id) : [...goals, id];
    if (next.length <= MAX_GOALS) update({ goals: next, ranking: [] });
  };
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink/70">Pick up to {MAX_GOALS}.</p>
      <div className="flex flex-wrap gap-2">
        {GOAL_CHOICES.map((g) => (
          <button
            key={g.id}
            type="button"
            className={chip(goals.includes(g.id))}
            aria-pressed={goals.includes(g.id)}
            onClick={() => toggle(g.id)}
          >
            {g.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export function Priority() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const ranked = rankedGoalTypes(answers);
  const move = (i: number, by: number) => {
    const next = [...ranked];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    update({ ranking: next });
  };
  return (
    <div className="space-y-3">
      <p className="text-sm text-ink/70">Your top goal sets your calories.</p>
      <ol className="space-y-2">
        {ranked.map((type, i) => (
          <li
            key={type}
            className="flex items-center justify-between rounded-lg border border-ink/15 bg-white px-3 py-2"
          >
            <span>
              {i + 1}. {GOAL_LABELS[type]}
            </span>
            <span className="flex gap-1">
              <button
                type="button"
                aria-label="Move up"
                disabled={i === 0}
                className="rounded px-2 disabled:opacity-30"
                onClick={() => move(i, -1)}
              >
                ↑
              </button>
              <button
                type="button"
                aria-label="Move down"
                disabled={i === ranked.length - 1}
                className="rounded px-2 disabled:opacity-30"
                onClick={() => move(i, 1)}
              >
                ↓
              </button>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function Placeholder({ captures, keys }: { captures: string[]; keys: (keyof Answers)[] }) {
  const answers = useAnswers((s) => s.answers);
  const current = Object.fromEntries(keys.map((k) => [k, answers[k]]));
  return (
    <div className="space-y-4 text-sm">
      <p className="text-ink/70">
        Placeholder screen. Captures <code>{captures.join(", ")}</code>.
      </p>
      <pre className="overflow-x-auto rounded-lg bg-white p-3 text-xs">
        {JSON.stringify(current, null, 2)}
      </pre>
    </div>
  );
}

export function GoalDetails() {
  const answers = useAnswers((s) => s.answers);
  return (
    <div className="space-y-2">
      <p className="text-sm text-ink/70">
        For: {goalTypes(answers.goals).map((t) => GOAL_LABELS[t]).join(", ")}
      </p>
      <Placeholder
        captures={["goals[].target_weight_kg", "goals[].event", "goals[].event_date"]}
        keys={["goalDetails"]}
      />
    </div>
  );
}

export const About = () => (
  <Placeholder
    captures={["profile.sex", "age", "height_cm", "weight_kg", "body_fat_pct"]}
    keys={["units", "sex", "birthDate", "weight", "heightCm", "heightFt", "heightIn", "bodyFatPct"]}
  />
);
export const Activity = () => <Placeholder captures={["profile.activity"]} keys={["activity"]} />;
export const Training = () => (
  <Placeholder
    captures={["profile.training.resistance", "weekly_schedule", "experience"]}
    keys={["training"]}
  />
);
export const Health = () => <Placeholder captures={["profile.flags"]} keys={["health"]} />;
export const Eating = () => (
  <Placeholder
    captures={["preferences.pattern_pref", "constraints.diet"]}
    keys={["eatingStyle"]}
  />
);
export const Avoid = () => (
  <Placeholder
    captures={["constraints.allergens", "religious", "preferences.dislikes"]}
    keys={["allergens", "religious", "dislikes"]}
  />
);
export const Taste = () => (
  <Placeholder
    captures={["preferences.taste", "cuisines", "cook_time_min", "budget"]}
    keys={["taste", "cuisines", "cookTimeMin", "budget"]}
  />
);
export const Pace = () => <Placeholder captures={["goals[].rate_pct_bw_week"]} keys={["pace"]} />;
export const Building = () => (
  <p className="text-sm text-ink/70">Safety → goals → targets → score. (Calls the API in Task 20.)</p>
);

function today(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function Results() {
  const answers = useAnswers((s) => s.answers);
  const request = useMemo(() => {
    try {
      return mapAnswers(answers, { asOf: today() });
    } catch (e) {
      return { error: (e as Error).message };
    }
  }, [answers]);
  return (
    <div className="space-y-3 text-sm">
      <p className="text-ink/70">The results screen comes in Task 20. This is the request it sends:</p>
      <pre className="max-h-96 overflow-auto rounded-lg bg-white p-3 text-xs">
        {JSON.stringify(request, null, 2)}
      </pre>
    </div>
  );
}
