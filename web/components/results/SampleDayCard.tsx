"use client";

// Sample day (Task 21): meals from POST /v1/recommendations/day for the selected phase and day
// type. Renders API fields only; the engine chooses foods, portions and the ±tolerance check.

import { useEffect, useState } from "react";

import type { PlanRequest } from "@/lib/onboarding/mapAnswers";
import { DAY_LABELS, title, whole } from "@/lib/results/format";
import {
  fetchSampleDay,
  MACRO_LABELS,
  SLOT_LABELS,
  signedPct,
  type SampleDay,
} from "@/lib/results/sampleDay";

import { Card, PENDING, Recommended, Why } from "./common";

// The last answer, for the phase and day type it was fetched for; any other key is loading.
type Result =
  | { key: string; kind: "error"; message: string }
  | { key: string; kind: "ready"; day: SampleDay | null };

export function SampleDayCard({
  request,
  phase,
  day,
  pending,
}: {
  request: PlanRequest;
  phase: string;
  day: string;
  pending: boolean;
}) {
  const key = `${phase}/${day}`;
  const [result, setResult] = useState<Result | null>(null);
  const state = result?.key === key ? result : { kind: "loading" as const };

  useEffect(() => {
    const controller = new AbortController();
    fetchSampleDay(request, day, phase, controller.signal)
      .then((d) => setResult({ key, kind: "ready", day: d }))
      .catch((e: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ key, kind: "error", message: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => controller.abort();
  }, [request, phase, day, key]);

  return (
    <section aria-labelledby="sample-day-heading" className="space-y-4">
      <h2 id="sample-day-heading" className="text-lg font-semibold">
        Sample day
      </h2>
      <Card className="space-y-4">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-medium">
            {DAY_LABELS[day] ?? title(day)} day · {title(phase)}
          </h3>
          <Recommended />
        </div>
        {pending ? (
          <p className="rounded-xl bg-mist p-4 text-sm">{PENDING}</p>
        ) : state.kind === "loading" ? (
          <div className="h-32 animate-pulse rounded-xl bg-mist" aria-busy="true" />
        ) : state.kind === "error" ? (
          <p className="text-sm text-ink/70">{state.message}</p>
        ) : state.day ? (
          <DayBody sample={state.day} />
        ) : (
          <p className="text-sm text-ink/70">No sample day for this plan.</p>
        )}
      </Card>
    </section>
  );
}

function DayBody({ sample }: { sample: SampleDay }) {
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {(["kcal", "protein_g", "carb_g", "fat_g"] as const).map((m) => (
          <div key={m} className="rounded-xl bg-mist p-3">
            <dt className="text-xs text-ink/60">{MACRO_LABELS[m]}</dt>
            <dd className="text-lg font-semibold">
              {whole(sample.nutrients[m])}
              <span className="ml-1 text-xs font-normal text-ink/60">
                / {whole(sample.targets[m])} {m === "kcal" ? "kcal" : "g"}
              </span>
            </dd>
            <dd className="text-xs text-ink/60">{signedPct(sample.deviation_pct[m] ?? 0)}</dd>
          </div>
        ))}
      </dl>
      <Why why={sample.why} ruleIds={sample.rule_ids} />

      <ol className="space-y-3">
        {sample.meals.map((meal) => (
          <li key={meal.slot} className="space-y-2 rounded-xl border border-ink/10 p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-medium">{SLOT_LABELS[meal.slot] ?? title(meal.slot)}</p>
              <p className="text-xs text-ink/60">
                {whole(meal.nutrients.kcal)} kcal · {whole(meal.nutrients.protein_g)} g protein ·{" "}
                {whole(meal.nutrients.carb_g)} g carbs · {whole(meal.nutrients.fat_g)} g fat
              </p>
            </div>
            <ul className="space-y-1 text-sm">
              {meal.items.map((item) => (
                <li key={item.key} className="flex justify-between gap-3">
                  <span title={item.why}>{item.name}</span>
                  <span className="shrink-0 text-ink/60 tabular-nums">{whole(item.grams)} g</span>
                </li>
              ))}
            </ul>
            <Why why={meal.why} ruleIds={meal.rule_ids} />
          </li>
        ))}
      </ol>
    </div>
  );
}
