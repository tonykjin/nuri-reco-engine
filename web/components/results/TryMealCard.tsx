"use client";

// Try a meal (Task 23): pick 2-4 foods with grams and score them with POST /v1/score/evaluate.
// Renders API fields only; the engine holds the nutrients, targets and formulas.

import { useEffect, useMemo, useState } from "react";

import type { PlanRequest } from "@/lib/onboarding/mapAnswers";
import { DAY_LABELS, num, target, title, whole } from "@/lib/results/format";
import {
  canScore,
  componentLabel,
  evaluateMeal,
  fetchFoods,
  LEFT_OUT_REASONS,
  MAX_FOODS,
  MIN_FOODS,
  STARTER_MEAL,
  type ComponentScore,
  type FoodListing,
  type MealRow,
  type ScoreEvaluation,
} from "@/lib/results/tryMeal";

import { Card, PENDING, Why } from "./common";

interface Row extends MealRow {
  // What the user typed; null shows the picked food's name.
  text: string | null;
}

type Result =
  | { key: string; kind: "loading" }
  | { key: string; kind: "error"; message: string }
  | { key: string; kind: "ready"; evaluation: ScoreEvaluation | null };

export function TryMealCard({
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
  const [foods, setFoods] = useState<FoodListing[] | null>(null);
  const [foodsError, setFoodsError] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>(STARTER_MEAL.map((r) => ({ ...r, text: null })));
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchFoods(controller.signal)
      .then(setFoods)
      .catch((e: unknown) => {
        if (!controller.signal.aborted) setFoodsError(e instanceof Error ? e.message : String(e));
      });
    return () => controller.abort();
  }, []);

  const byKey = useMemo(() => new Map((foods ?? []).map((f) => [f.key, f])), [foods]);
  const byName = useMemo(() => new Map((foods ?? []).map((f) => [f.name, f])), [foods]);

  const key = `${phase}/${day}/${JSON.stringify(rows.map((r) => [r.key, r.grams]))}`;
  const shown = result?.key === key ? result : null;
  const ready = canScore(rows);

  const update = (i: number, change: Partial<Row>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...change } : r)));

  const score = () => {
    setResult({ key, kind: "loading" });
    evaluateMeal(request, rows, day, phase)
      .then((evaluation) => setResult({ key, kind: "ready", evaluation }))
      .catch((e: unknown) =>
        setResult({ key, kind: "error", message: e instanceof Error ? e.message : String(e) }),
      );
  };

  return (
    <section aria-labelledby="try-meal-heading" className="space-y-4">
      <h2 id="try-meal-heading" className="text-lg font-semibold">
        Try a meal
      </h2>
      <Card className="space-y-4">
        <p className="text-sm text-ink/70">
          Pick {MIN_FOODS}–{MAX_FOODS} foods to see how a meal scores for your{" "}
          {(DAY_LABELS[day] ?? title(day)).toLowerCase()} days in the {title(phase).toLowerCase()}{" "}
          phase.
        </p>
        {pending ? (
          <p className="rounded-xl bg-mist p-4 text-sm">{PENDING}</p>
        ) : foodsError ? (
          <p className="text-sm text-ink/70">{foodsError}</p>
        ) : (
          <>
            <datalist id="try-meal-foods">
              {(foods ?? []).map((f) => (
                <option key={f.key} value={f.name} />
              ))}
            </datalist>
            <ul className="space-y-2">
              {rows.map((row, i) => (
                <li key={i} className="flex items-center gap-2">
                  <input
                    aria-label={`Food ${i + 1}`}
                    list="try-meal-foods"
                    className="min-w-0 flex-1 rounded-xl border border-ink/20 px-3 py-2 text-sm"
                    placeholder={foods ? "Search foods" : "Loading foods…"}
                    value={row.text ?? (row.key ? (byKey.get(row.key)?.name ?? "") : "")}
                    onChange={(e) =>
                      update(i, {
                        text: e.target.value,
                        key: byName.get(e.target.value)?.key ?? null,
                      })
                    }
                  />
                  <input
                    aria-label={`Grams of food ${i + 1}`}
                    type="number"
                    min={1}
                    inputMode="numeric"
                    className="w-20 rounded-xl border border-ink/20 px-3 py-2 text-right text-sm tabular-nums"
                    value={row.grams ?? ""}
                    onChange={(e) =>
                      update(i, { grams: e.target.value === "" ? null : Number(e.target.value) })
                    }
                  />
                  <span className="text-sm text-ink/60">g</span>
                  <button
                    type="button"
                    aria-label={`Remove food ${i + 1}`}
                    className="rounded-full px-2 text-ink/50 hover:text-ink disabled:opacity-30"
                    disabled={rows.length <= MIN_FOODS}
                    onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className="rounded-full bg-mist px-4 py-2 text-sm disabled:opacity-40"
                disabled={rows.length >= MAX_FOODS}
                onClick={() => setRows((rs) => [...rs, { key: null, grams: null, text: null }])}
              >
                Add a food
              </button>
              <button
                type="button"
                className="rounded-full bg-ink px-4 py-2 text-sm text-white disabled:opacity-40"
                disabled={!ready || shown?.kind === "loading"}
                onClick={score}
              >
                Score this meal
              </button>
            </div>
            {shown?.kind === "loading" && (
              <div className="h-32 animate-pulse rounded-xl bg-mist" aria-busy="true" />
            )}
            {shown?.kind === "error" && <p className="text-sm text-ink/70">{shown.message}</p>}
            {shown?.kind === "ready" &&
              (shown.evaluation ? (
                <MealScore evaluation={shown.evaluation} />
              ) : (
                <p className="text-sm text-ink/70">No score for this plan.</p>
              ))}
          </>
        )}
      </Card>
    </section>
  );
}

function MealScore({ evaluation: ev }: { evaluation: ScoreEvaluation }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <div className="rounded-xl bg-mist p-3">
          <p className="text-xs text-ink/60">Meal score</p>
          <p className="text-2xl font-semibold">{ev.score == null ? "—" : whole(ev.score)}</p>
        </div>
        <div className="rounded-xl bg-mist p-3">
          <p className="text-xs text-ink/60">Data coverage</p>
          <p className="text-2xl font-semibold">{whole(ev.coverage_pct)}%</p>
        </div>
      </div>
      <p className="text-xs text-ink/60">
        {whole(ev.energy_kcal)} kcal, {whole(ev.energy_share * 100)}% of your{" "}
        {whole(ev.day_energy_kcal)} kcal day. Targets below are this meal&apos;s share.
      </p>
      <ul className="space-y-3">
        {ev.components.map((c) => (
          <ComponentRow key={c.id} c={c} />
        ))}
        {(ev.left_out ?? []).map((o) => (
          <li key={o.id} className="text-sm text-ink/50">
            {componentLabel(o.id)}: {LEFT_OUT_REASONS[o.reason] ?? o.reason}
          </li>
        ))}
      </ul>
      <Why why={ev.why} ruleIds={ev.rule_ids} />
    </div>
  );
}

function ComponentRow({ c }: { c: ComponentScore }) {
  const unit = c.target.unit;
  return (
    <li className="space-y-1">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium">{componentLabel(c.id)}</span>
        <span className="shrink-0 text-xs text-ink/60 tabular-nums">
          {c.available && c.contribution != null
            ? `+${num(c.contribution)} pts of ${num(c.weight)}`
            : `no data · weight ${num(c.weight)}`}
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-mist"
        role="img"
        aria-label={c.score == null ? "no data" : `score ${whole(c.score)} of 100`}
      >
        {c.score != null && (
          <div className="h-full rounded-full bg-signal" style={{ width: `${c.score}%` }} />
        )}
      </div>
      <p className="text-xs text-ink/60">
        {c.actual == null ? "No data for one of these foods" : `${num(c.actual)} ${unit}`} · target{" "}
        {target(c.target)}
      </p>
      <Why why={c.why} ruleIds={c.rule_ids} />
    </li>
  );
}
