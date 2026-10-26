"use client";

// What to eat (Task 24, spec §6, §7.4): diet pattern cards from PlanResponse.patterns and the
// ranked food list from POST /v1/recommendations/foods, re-queried when the filters or the mock
// pantry change. No ranking logic here: the engine ranks, boosts and explains.

import { useEffect, useMemo, useState } from "react";

import type { PlanRequest } from "@/lib/onboarding/mapAnswers";
import { DAY_LABELS, title, type PlanResponse } from "@/lib/results/format";
import { fetchFoods, type FoodListing } from "@/lib/results/tryMeal";
import {
  fetchRankedFoods,
  foodContext,
  MEAL_SLOT_LABELS,
  RIPENESS_LABELS,
  upsertPantry,
  type FoodRecommendation,
  type MealSlot,
  type PantryItem,
  type Ripeness,
} from "@/lib/results/whatToEat";

import { Card, Recommended, Why } from "./common";

type Result =
  | { key: string; kind: "error"; message: string }
  | { key: string; kind: "ready"; foods: FoodRecommendation[] };

export function WhatToEat({
  response,
  request,
  phase,
  dayTypes,
  day,
  onDay,
}: {
  response: PlanResponse;
  request: PlanRequest;
  phase: string;
  dayTypes: string[];
  day: string;
  onDay: (day: string) => void;
}) {
  const [slot, setSlot] = useState<MealSlot>("any");
  const [pantry, setPantry] = useState<PantryItem[]>([]);
  const [result, setResult] = useState<Result | null>(null);

  const context = useMemo(() => foodContext(slot, day, phase, pantry), [slot, day, phase, pantry]);
  const key = JSON.stringify(context);
  const state = result?.key === key ? result : { kind: "loading" as const };

  useEffect(() => {
    const controller = new AbortController();
    fetchRankedFoods(request, context, controller.signal)
      .then((foods) => setResult({ key, kind: "ready", foods }))
      .catch((e: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ key, kind: "error", message: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => controller.abort();
  }, [request, context, key]);

  const patterns = response.patterns ?? [];
  const inPantry = new Set(pantry.map((p) => p.key));

  return (
    <div className="space-y-8">
      <section aria-labelledby="patterns-heading" className="space-y-3">
        <h2 id="patterns-heading" className="text-lg font-semibold">
          Eating patterns that fit you
        </h2>
        {patterns.length === 0 ? (
          <p className="text-sm text-ink/70">No eating pattern for this plan yet.</p>
        ) : (
          <ol className="grid gap-3 sm:grid-cols-3">
            {patterns.map((p, i) => (
              <li key={p.id}>
                <Card className={`h-full space-y-2 ${i === 0 ? "ring-2 ring-signal" : ""}`}>
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-xs text-ink/60">{i === 0 ? "Best fit" : "Alternative"}</p>
                    <Recommended />
                  </div>
                  <h3 className="font-medium">{p.name}</h3>
                  <Why why={p.why} ruleIds={p.rule_ids} />
                </Card>
              </li>
            ))}
          </ol>
        )}
      </section>

      <section aria-labelledby="foods-heading" className="space-y-3">
        <h2 id="foods-heading" className="text-lg font-semibold">
          Foods for you
        </h2>
        <Card className="flex flex-wrap gap-4">
          <label className="space-y-1 text-sm">
            <span className="block text-ink/60">Meal</span>
            <select
              className="rounded-xl border border-ink/20 bg-white px-3 py-2"
              value={slot}
              onChange={(e) => setSlot(e.target.value as MealSlot)}
            >
              {Object.entries(MEAL_SLOT_LABELS).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="block text-ink/60">Day</span>
            <select
              className="rounded-xl border border-ink/20 bg-white px-3 py-2"
              value={day}
              onChange={(e) => onDay(e.target.value)}
            >
              {dayTypes.map((d) => (
                <option key={d} value={d}>
                  {DAY_LABELS[d] ?? title(d)}
                </option>
              ))}
            </select>
          </label>
        </Card>

        <PantryPanel pantry={pantry} onChange={setPantry} />

        {state.kind === "loading" ? (
          <div className="h-64 animate-pulse rounded-2xl bg-mist" aria-busy="true" />
        ) : state.kind === "error" ? (
          <p className="text-sm text-ink/70">{state.message}</p>
        ) : state.foods.length === 0 ? (
          <p className="text-sm text-ink/70">No foods match these filters.</p>
        ) : (
          <ol className="space-y-2">
            {state.foods.map((f, i) => (
              <li key={f.key}>
                <Card className={`space-y-2 ${inPantry.has(f.key) ? "ring-2 ring-signal/60" : ""}`}>
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-medium">
                      <span className="mr-2 text-ink/40 tabular-nums">{i + 1}.</span>
                      {f.name}
                    </p>
                    <Recommended />
                  </div>
                  {(f.reasons ?? []).length > 0 && (
                    <ul className="flex flex-wrap gap-1.5">
                      {(f.reasons ?? []).map((r) => (
                        <li key={r} className="rounded-full bg-mist px-2.5 py-0.5 text-xs">
                          {r}
                        </li>
                      ))}
                    </ul>
                  )}
                  <Why why={f.why} ruleIds={f.rule_ids} />
                </Card>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

function PantryPanel({
  pantry,
  onChange,
}: {
  pantry: PantryItem[];
  onChange: (pantry: PantryItem[]) => void;
}) {
  const [foods, setFoods] = useState<FoodListing[] | null>(null);
  const [text, setText] = useState("");
  const [ripeness, setRipeness] = useState<Ripeness | "">("");
  const [peaks, setPeaks] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchFoods(controller.signal)
      .then(setFoods)
      .catch(() => setFoods([]));
    return () => controller.abort();
  }, []);

  const byName = useMemo(() => new Map((foods ?? []).map((f) => [f.name, f])), [foods]);
  const byKey = useMemo(() => new Map((foods ?? []).map((f) => [f.key, f])), [foods]);
  const picked = byName.get(text);

  const add = () => {
    if (!picked) return;
    onChange(
      upsertPantry(pantry, { key: picked.key, ripeness: ripeness || null, peaks_tonight: peaks }),
    );
    setText("");
    setRipeness("");
    setPeaks(false);
  };

  return (
    <Card className="space-y-3">
      <div>
        <h3 className="font-medium">Your pantry (demo)</h3>
        <p className="text-sm text-ink/70">
          Add what&apos;s at home and how ripe it is. Pantry foods, especially ones that peak
          tonight, move up the list.
        </p>
      </div>
      <datalist id="pantry-foods">
        {(foods ?? []).map((f) => (
          <option key={f.key} value={f.name} />
        ))}
      </datalist>
      <div className="flex flex-wrap items-end gap-2">
        <input
          aria-label="Pantry food"
          list="pantry-foods"
          className="min-w-0 flex-1 rounded-xl border border-ink/20 px-3 py-2 text-sm"
          placeholder={foods ? "Search foods" : "Loading foods…"}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <select
          aria-label="Ripeness"
          className="rounded-xl border border-ink/20 bg-white px-3 py-2 text-sm"
          value={ripeness}
          onChange={(e) => setRipeness(e.target.value as Ripeness | "")}
        >
          <option value="">Ripeness unknown</option>
          {Object.entries(RIPENESS_LABELS).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={peaks} onChange={(e) => setPeaks(e.target.checked)} />
          Peaks tonight
        </label>
        <button
          type="button"
          className="rounded-full bg-ink px-4 py-2 text-sm text-white disabled:opacity-40"
          disabled={!picked}
          onClick={add}
        >
          Add
        </button>
      </div>
      {pantry.length > 0 && (
        <ul className="space-y-1">
          {pantry.map((item) => (
            <li key={item.key} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="min-w-0 flex-1">{byKey.get(item.key)?.name ?? item.key}</span>
              <select
                aria-label={`Ripeness of ${byKey.get(item.key)?.name ?? item.key}`}
                className="rounded-lg border border-ink/20 bg-white px-2 py-1 text-xs"
                value={item.ripeness ?? ""}
                onChange={(e) =>
                  onChange(
                    upsertPantry(pantry, {
                      ...item,
                      ripeness: (e.target.value || null) as Ripeness | null,
                    }),
                  )
                }
              >
                <option value="">Ripeness unknown</option>
                {Object.entries(RIPENESS_LABELS).map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1 text-xs">
                <input
                  type="checkbox"
                  checked={item.peaks_tonight ?? false}
                  onChange={(e) =>
                    onChange(upsertPantry(pantry, { ...item, peaks_tonight: e.target.checked }))
                  }
                />
                Peaks tonight
              </label>
              <button
                type="button"
                aria-label={`Remove ${byKey.get(item.key)?.name ?? item.key}`}
                className="px-2 text-ink/50 hover:text-ink"
                onClick={() => onChange(pantry.filter((p) => p.key !== item.key))}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
