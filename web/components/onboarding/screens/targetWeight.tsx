"use client";

// Pick a target weight (spec §11.3 screen 9; engine rules §4.4b). Comes after the health check so
// the engine can hide the number when it should. The range, bounds, default and every sentence
// come from POST /v1/goals/weight-range; this screen converts units and snaps to the step.

import { useEffect, useMemo, useState } from "react";

import {
  type Answers,
  GOAL_LABELS,
  type GoalType,
  rankedGoalTypes,
  WEIGHT_GOALS,
} from "@/lib/onboarding/answers";
import { mapAnswers } from "@/lib/onboarding/mapAnswers";
import { useAnswers } from "@/lib/onboarding/store";
import { today } from "@/lib/onboarding/validation";
import {
  fetchWeightRange,
  inBand,
  type SliderModel,
  sliderModel,
  snap,
  type TargetBounds,
  toDisplay,
  type WeightRangeResponse,
  withoutTargets,
} from "@/lib/onboarding/weightRange";

import { Helper, Label } from "../ui";

type Result =
  | { key: string; kind: "error"; message: string }
  | { key: string; kind: "ready"; response: WeightRangeResponse };

const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

function unitLabels(units: Answers["units"]) {
  return units === "metric" ? { short: "kg", long: "kilograms" } : { short: "lb", long: "pounds" };
}

/** A kg band in display units, rounded inward (0.1 kg, 1 lb). */
function bandText(band: { min_kg: number; max_kg: number }, units: Answers["units"]) {
  const step = units === "metric" ? 0.1 : 1;
  const low = Math.ceil(toDisplay(band.min_kg, units) / step - 1e-9) * step;
  const high = Math.floor(toDisplay(band.max_kg, units) / step + 1e-9) * step;
  return `${fmt(Math.round(low * 10) / 10)}–${fmt(Math.round(high * 10) / 10)} ${unitLabels(units).short}`;
}

export function TargetWeight() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState<Result | null>(null);

  // Targets are cleared, so moving the slider doesn't refetch.
  const request = useMemo(() => {
    try {
      return withoutTargets(mapAnswers(answers, { asOf: today() }));
    } catch {
      return null;
    }
  }, [answers]);
  const key = `${JSON.stringify(request)}#${attempt}`;
  const state = result?.key === key ? result : { kind: "loading" as const };

  useEffect(() => {
    if (!request) return;
    const controller = new AbortController();
    fetchWeightRange(request, controller.signal)
      .then((response) => setResult({ key, kind: "ready", response }))
      .catch((e: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ key, kind: "error", message: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => controller.abort();
  }, [request, key]);

  const weightGoals = rankedGoalTypes(answers).filter((t) => WEIGHT_GOALS.includes(t));
  const hidden = state.kind === "ready" && state.response.status === "hidden";

  // Number-hiding mode: no target weight is kept.
  useEffect(() => {
    if (!hidden) return;
    const set = weightGoals.filter((t) => answers.goalDetails[t]?.targetWeight != null);
    if (set.length === 0) return;
    update({
      goalDetails: {
        ...answers.goalDetails,
        ...Object.fromEntries(
          set.map((t) => [t, { ...answers.goalDetails[t], targetWeight: null }]),
        ),
      },
    });
  }, [hidden, weightGoals, answers.goalDetails, update]);

  if (!request) {
    return <Helper>Some earlier answers are missing. Go back to fill them in.</Helper>;
  }
  if (state.kind === "loading") {
    return <div className="h-64 animate-pulse rounded-2xl bg-white" aria-busy="true" />;
  }
  if (state.kind === "error") {
    return (
      <div className="space-y-3">
        <p className="text-sm text-signal">Couldn&apos;t load your range: {state.message}</p>
        <button
          type="button"
          className="min-h-11 rounded-full bg-ink px-5 text-sm text-white"
          onClick={() => setAttempt((n) => n + 1)}
        >
          Retry
        </button>
      </div>
    );
  }

  const { response } = state;
  if (response.status === "blocked") {
    return (
      <p className="rounded-xl bg-white p-4 text-sm">
        We&apos;ll explain your next step on the results screen.
      </p>
    );
  }
  if (response.status === "hidden") {
    return <p className="rounded-xl bg-white p-4 text-sm">{response.why}</p>;
  }

  const setTarget = (type: GoalType, targetWeight: number | null) =>
    update({
      goalDetails: {
        ...answers.goalDetails,
        [type]: { ...answers.goalDetails[type], targetWeight },
      },
    });

  return (
    <div className="space-y-6">
      <Helper>Optional. Not sure? Start with our suggestion; you can change it later.</Helper>
      {response.recommended && (
        <div className="space-y-1 rounded-xl bg-white p-4">
          <p className="text-sm font-medium">
            Recommended: {bandText(response.recommended, answers.units)}
          </p>
          <p className="text-sm text-ink/70">{response.recommended.why}</p>
          {response.milestone && (
            <p className="text-sm text-ink/70">
              First milestone: {bandText(response.milestone, answers.units)}.{" "}
              {response.milestone.why}
            </p>
          )}
        </div>
      )}
      {weightGoals.map((type) => {
        const bounds = response.target_bounds?.[type];
        return bounds ? (
          <GoalSlider
            key={type}
            type={type}
            bounds={bounds}
            response={response}
            units={answers.units}
            value={answers.goalDetails[type]?.targetWeight ?? null}
            onChange={(v) => setTarget(type, v)}
          />
        ) : (
          <section key={type} className="space-y-2 rounded-xl bg-white p-4">
            <Label>{GOAL_LABELS[type]}</Label>
            <p className="text-sm text-ink/70">{response.why}</p>
          </section>
        );
      })}
    </div>
  );
}

function GoalSlider({
  type,
  bounds,
  response,
  units,
  value,
  onChange,
}: {
  type: GoalType;
  bounds: TargetBounds;
  response: WeightRangeResponse;
  units: Answers["units"];
  value: number | null;
  onChange: (value: number | null) => void;
}) {
  const model: SliderModel = sliderModel(bounds, response.recommended, response.milestone, units);
  const chosen = value !== null && value >= model.min && value <= model.max;
  const shown = chosen ? value : model.defaultValue;
  const unit = unitLabels(units);
  const inside = inBand(shown, response.recommended, units);
  const move = (by: number) => onChange(snap(shown + by * model.step, model));

  return (
    <section className="space-y-4 rounded-xl bg-white p-5">
      <div className="flex items-baseline justify-between gap-3">
        <Label>{GOAL_LABELS[type]}</Label>
        <span className="text-xs text-ink/60">{chosen ? "Your target" : "Suggested"}</span>
      </div>
      <div className="flex items-center justify-between gap-3">
        <button
          type="button"
          aria-label={`Lower by ${model.step} ${unit.short}`}
          disabled={shown <= model.min}
          className="size-11 rounded-full bg-mist text-xl disabled:opacity-30"
          onClick={() => move(-1)}
        >
          −
        </button>
        <p className="text-3xl font-semibold tabular-nums">
          {fmt(shown)} <span className="text-base font-normal text-ink/60">{unit.short}</span>
        </p>
        <button
          type="button"
          aria-label={`Raise by ${model.step} ${unit.short}`}
          disabled={shown >= model.max}
          className="size-11 rounded-full bg-mist text-xl disabled:opacity-30"
          onClick={() => move(1)}
        >
          +
        </button>
      </div>

      <div className="space-y-1">
        {/* The bands sit under the slider; mx-2 lines them up with the thumb's travel. */}
        <div className="relative mx-2 h-2 rounded-full bg-mist" aria-hidden="true">
          {model.bands.map((b) => (
            <span
              key={b.kind}
              className={`absolute inset-y-0 rounded-full ${
                b.kind === "recommended" ? "bg-signal/25" : "bg-signal/70"
              }`}
              style={{ left: `${b.fromPct}%`, width: `${b.toPct - b.fromPct}%` }}
            />
          ))}
        </div>
        <input
          type="range"
          min={model.min}
          max={model.max}
          step={model.step}
          value={shown}
          aria-label={`${GOAL_LABELS[type]}: target weight`}
          aria-valuetext={`${fmt(shown)} ${unit.long}, ${inside ? "inside" : "outside"} the recommended range`}
          className="w-full accent-signal"
          onChange={(e) => onChange(snap(Number(e.target.value), model))}
        />
        <div className="flex justify-between text-xs text-ink/60">
          <span>
            {fmt(model.min)} {unit.short}
          </span>
          <span>
            {fmt(model.max)} {unit.short}
          </span>
        </div>
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink/70">
          {model.bands.map((b) => (
            <li key={b.kind} className="flex items-center gap-1.5">
              <span
                className={`inline-block size-2.5 rounded-full ${
                  b.kind === "recommended" ? "bg-signal/25" : "bg-signal/70"
                }`}
              />
              {b.kind === "recommended" ? "Recommended range" : "First milestone"}
            </li>
          ))}
        </ul>
      </div>

      <p className="text-sm text-ink/70">{bounds.why}</p>
      <div className="flex flex-wrap gap-x-5 gap-y-2 text-sm">
        {!chosen && (
          <button
            type="button"
            className="text-signal underline"
            onClick={() => onChange(model.defaultValue)}
          >
            Use the suggested weight
          </button>
        )}
        <button
          type="button"
          className="text-ink/60 underline disabled:no-underline disabled:opacity-40"
          disabled={value === null}
          onClick={() => onChange(null)}
        >
          Skip, no target weight
        </button>
      </div>
    </section>
  );
}
