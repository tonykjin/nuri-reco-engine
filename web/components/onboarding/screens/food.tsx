"use client";

import { useState } from "react";

import {
  ALLERGENS,
  BUDGETS,
  COOK_TIMES,
  CUISINES,
  EATING_STYLES,
  MEALS,
  RELIGIOUS,
  SNACKS,
  TASTE_DIMENSIONS,
} from "@/lib/onboarding/options";
import { useAnswers } from "@/lib/onboarding/store";

import { useStepNav } from "../nav";
import { ChoiceList, Chips, Helper, Label, toggle } from "../ui";

export function Eating() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  // Single select; tapping the chosen chip clears it (like Days per week on Training).
  const pick = (current: number | null, id: string) => (current === Number(id) ? null : Number(id));
  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <Helper>Pick the one that sounds most like you.</Helper>
        <ChoiceList
          options={EATING_STYLES}
          value={answers.eatingStyle}
          onChange={(e) => update({ eatingStyle: e })}
        />
      </div>
      <section className="space-y-2">
        <Label>How many meals do you usually eat a day?</Label>
        <Chips
          options={MEALS}
          values={answers.mealsPerDay === null ? [] : [String(answers.mealsPerDay)]}
          onToggle={(id) => update({ mealsPerDay: pick(answers.mealsPerDay, id) })}
        />
      </section>
      <section className="space-y-2">
        <Label>And snacks?</Label>
        <Chips
          options={SNACKS}
          values={answers.snacksPerDay === null ? [] : [String(answers.snacksPerDay)]}
          onToggle={(id) => update({ snacksPerDay: pick(answers.snacksPerDay, id) })}
        />
        <Helper>Optional. We&apos;ll spread your protein across the meals you actually eat.</Helper>
      </section>
    </div>
  );
}

const splitList = (text: string) =>
  text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

export function Avoid() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const [dislikes, setDislikes] = useState(answers.dislikes.join(", "));
  return (
    <div className="space-y-6">
      <Helper>Allergens are never recommended. Dislikes just show up less.</Helper>
      <section className="space-y-2">
        <Label>Allergies</Label>
        <Chips
          options={ALLERGENS}
          values={answers.allergens}
          onToggle={(id) => update({ allergens: toggle(answers.allergens, id) })}
        />
      </section>
      <section className="space-y-2">
        <Label>Religious or cultural rules</Label>
        <Chips
          options={RELIGIOUS}
          values={answers.religious}
          onToggle={(id) => update({ religious: toggle(answers.religious, id) })}
        />
      </section>
      <label className="block space-y-2">
        <Label>Foods you&apos;d rather skip</Label>
        <input
          className="min-h-14 w-full rounded-xl bg-white px-4"
          placeholder="e.g. cottage cheese, olives"
          value={dislikes}
          onChange={(e) => {
            setDislikes(e.target.value);
            update({ dislikes: splitList(e.target.value) });
          }}
        />
      </label>
    </div>
  );
}

export function Taste() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const { next } = useStepNav();

  const skip = () => {
    update({ taste: {}, cuisines: [], cookTimeMin: null, budget: null });
    next();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <Helper>Optional. Move only the ones you care about.</Helper>
        <button type="button" className="shrink-0 text-sm text-signal underline" onClick={skip}>
          Skip
        </button>
      </div>
      <section className="space-y-4">
        {TASTE_DIMENSIONS.map((d) => {
          const value = answers.taste[d.id];
          return (
            <label key={d.id} className="block space-y-1 rounded-xl bg-white p-4">
              <span className="flex justify-between text-sm">
                <span className="font-medium">{d.label}</span>
                <span className="text-ink/50">{value === undefined ? "Not set" : ""}</span>
              </span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.1}
                value={value ?? 0.5}
                aria-label={d.label}
                className={`w-full accent-signal ${value === undefined ? "opacity-40" : ""}`}
                onChange={(e) =>
                  update({
                    taste: { ...answers.taste, [d.id]: Number(e.target.value) },
                  })
                }
              />
              <span className="flex justify-between text-xs text-ink/60">
                <span>{d.low}</span>
                <span>{d.high}</span>
              </span>
            </label>
          );
        })}
      </section>
      <section className="space-y-2">
        <Label>Cuisines you love</Label>
        <Chips
          options={CUISINES}
          values={answers.cuisines}
          onToggle={(id) => update({ cuisines: toggle(answers.cuisines, id) })}
        />
      </section>
      <section className="space-y-2">
        <Label>Time to cook</Label>
        <Chips
          options={COOK_TIMES.map((m) => ({
            id: String(m),
            label: `${m} min`,
          }))}
          values={answers.cookTimeMin ? [String(answers.cookTimeMin)] : []}
          onToggle={(id) =>
            update({
              cookTimeMin: answers.cookTimeMin === Number(id) ? null : Number(id),
            })
          }
        />
      </section>
      <section className="space-y-2">
        <Label>Food budget</Label>
        <Chips
          options={BUDGETS}
          values={answers.budget ? [answers.budget] : []}
          onToggle={(id) => update({ budget: answers.budget === id ? null : id })}
        />
      </section>
    </div>
  );
}
