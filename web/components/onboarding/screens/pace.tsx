"use client";

// Pick your pace: each change previews the plan with POST /v1/plan?dry_run=true (300 ms debounce).
// Every number shown comes from the engine; the slider bounds are display limits only.

import { useEffect, useMemo, useRef, useState } from "react";

import { latestOnly, type Latest } from "@/lib/onboarding/latest";
import { mapAnswers, type PlanRequest } from "@/lib/onboarding/mapAnswers";
import { PACE } from "@/lib/onboarding/options";
import { fetchPlan, type PlanResponse } from "@/lib/onboarding/plan";
import { useAnswers } from "@/lib/onboarding/store";
import { today } from "@/lib/onboarding/validation";

import { Helper } from "../ui";

const DEBOUNCE_MS = 300;
const LB_PER_KG = 1 / 0.45359237;

type Preview =
  | { state: "loading" }
  | { state: "ready"; response: PlanResponse }
  | { state: "error"; message: string };

function formatDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  return new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** The day type the user has most often (ties: first in the week). */
function commonDay(schedule: string[]): string {
  const counts = new Map<string, number>();
  schedule.forEach((d) => counts.set(d, (counts.get(d) ?? 0) + 1));
  return [...counts.entries()].reduce((a, b) => (b[1] > a[1] ? b : a))[0];
}

export function Pace() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const [preview, setPreview] = useState<Preview>({ state: "loading" });
  const latest = useRef<Latest<PlanRequest> | null>(null);

  const request = useMemo(() => {
    try {
      return mapAnswers(answers, { asOf: today() });
    } catch {
      return null;
    }
  }, [answers]);
  const key = JSON.stringify(request);

  useEffect(() => {
    latest.current = latestOnly(
      (req: PlanRequest, signal) => fetchPlan(req, { dryRun: true, signal }),
      DEBOUNCE_MS,
      {
        onResult: (response) => setPreview({ state: "ready", response }),
        onError: (e) => setPreview({ state: "error", message: (e as Error).message }),
      },
    );
    return () => latest.current?.cancel();
  }, []);

  useEffect(() => {
    if (request) latest.current?.call(request);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps -- `key` is `request` serialised

  if (!request) {
    return <Helper>Some earlier answers are missing. Go back to fill them in.</Helper>;
  }

  const response = preview.state === "ready" ? preview.response : null;
  const used = response?.goal_summary.pace.rate_pct_bw_week ?? null;
  const value = answers.pace ?? used ?? PACE.min;
  const held = response && (response.status === "blocked" || response.status === "rd_review");
  // Two different messages: the chosen pace was capped, or the date comes before the goal.
  const paceCapped = answers.pace !== null && used !== null && used < answers.pace - 1e-9;
  const dateTooSoon = response?.feasibility?.status === "clamped";

  const day = commonDay(answers.training.schedule);
  const targets = response?.phases?.[0]?.targets_by_day_type;
  const kcal = targets ? (targets[day] ?? Object.values(targets)[0])?.kcal : undefined;
  const projectedKg = response?.goal_summary.pace.projected_kg_at_event;
  const projected =
    projectedKg == null
      ? null
      : answers.units === "metric"
        ? `${projectedKg.toFixed(1)} kg`
        : `${(projectedKg * LB_PER_KG).toFixed(1)} lb`;
  const reachable = formatDate(response?.goal_summary.pace.reachable_date);

  return (
    <div className="space-y-6">
      <Helper>Faster isn&apos;t always better. Slide to see how your plan changes.</Helper>

      <div className="space-y-3 rounded-xl bg-white p-5">
        <div className="flex items-baseline justify-between">
          <span className="text-3xl font-semibold">{value.toFixed(2)}%</span>
          <span className="text-sm text-ink/60">of body weight per week</span>
        </div>
        <input
          type="range"
          min={PACE.min}
          max={PACE.max}
          step={PACE.step}
          value={value}
          aria-label="Weekly pace"
          className="w-full accent-signal"
          onChange={(e) => update({ pace: Number(e.target.value) })}
        />
        <div className="flex justify-between text-xs text-ink/60">
          <span>Steady</span>
          <span>Fast</span>
        </div>
        <button
          type="button"
          className="text-sm text-signal underline disabled:no-underline disabled:opacity-40"
          disabled={answers.pace === null}
          onClick={() => update({ pace: null })}
        >
          Use the recommended pace
        </button>
      </div>

      <div aria-live="polite" className="space-y-3">
        {preview.state === "loading" && <p className="text-sm text-ink/60">Updating your plan…</p>}
        {preview.state === "error" && (
          <p className="text-sm text-signal">Couldn&apos;t preview the plan: {preview.message}</p>
        )}
        {held && (
          <p className="rounded-xl bg-white p-4 text-sm">
            We&apos;ll explain your next step on the results screen.
          </p>
        )}
        {response && !held && (
          <>
            <dl className="grid grid-cols-2 gap-3">
              <Stat
                label="Calories a day"
                value={kcal ? `${Math.round(kcal / 10) * 10} kcal` : "–"}
              />
              <Stat label="Pace we'll use" value={used !== null ? `${used}% / week` : "–"} />
              {projected && <Stat label="On the day" value={projected} />}
              {reachable && <Stat label="Goal weight by" value={reachable} />}
            </dl>
            {(paceCapped || dateTooSoon) && (
              <div className="rounded-xl border-2 border-signal bg-white p-4 text-sm" role="status">
                <p className="font-medium">
                  {paceCapped
                    ? `That's faster than we recommend, so we'll use ${used}% a week.`
                    : "Your full goal will take a little longer than your date."}
                </p>
                <p className="mt-1 text-ink/80">{response.goal_summary.headline}</p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-white p-4">
      <dt className="text-xs text-ink/60">{label}</dt>
      <dd className="text-lg font-semibold">{value}</dd>
    </div>
  );
}
