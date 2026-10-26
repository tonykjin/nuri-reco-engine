"use client";

import {
  byDayOrder,
  DAY_LABELS,
  dateRange,
  ENERGY_LABELS,
  mealPattern,
  type Phase,
  type PlanResponse,
  title,
  weight,
  whole,
  date,
} from "@/lib/results/format";
import { GOAL_LABELS, type GoalType } from "@/lib/onboarding/answers";

import { Card, PENDING, Recommended, Tabs, Why } from "./common";

interface Props {
  response: PlanResponse;
  phase: Phase | undefined;
  onPhase: (name: string) => void;
  day: string;
  onDay: (day: string) => void;
  pending: boolean;
  units: "metric" | "imperial";
}

export function GoalsPanel({ response, phase, onPhase, day, onDay, pending, units }: Props) {
  const { goal_summary: summary, phases = [], feasibility } = response;
  const pace = summary.pace;
  const targets = phase?.targets_by_day_type ?? {};
  const days = Object.keys(targets).sort(byDayOrder);
  const t = targets[day] ?? targets[days[0]];

  return (
    <section aria-labelledby="goals-heading" className="space-y-4">
      <h2 id="goals-heading" className="text-xl font-semibold">
        Your goals
      </h2>

      <Card className="space-y-4">
        <ol className="space-y-4">
          {summary.goals.map((g) => (
            <li key={g.type} className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">
                  {GOAL_LABELS[g.type as GoalType] ?? title(g.type)}
                </span>
                <span
                  className={`rounded-full px-2 py-0.5 text-[11px] uppercase ${
                    g.role === "primary" ? "bg-signal text-white" : "bg-mist text-ink/70"
                  }`}
                >
                  {g.role}
                </span>
                <Recommended />
              </div>
              <p className="text-sm text-ink/80">{g.resolved_as}</p>
              <Why why={g.why} ruleIds={g.rule_ids} />
            </li>
          ))}
        </ol>
      </Card>

      {phases.length > 0 && (
        <Card className="space-y-3">
          <h3 className="font-medium">Your phases</h3>
          <ol className="space-y-2">
            {phases.map((p) => (
              <li key={p.name}>
                <button
                  type="button"
                  aria-pressed={p.name === phase?.name}
                  onClick={() => onPhase(p.name)}
                  className={`w-full rounded-xl border-2 px-3 py-2 text-left ${
                    p.name === phase?.name ? "border-ink" : "border-transparent bg-mist/60"
                  }`}
                >
                  <span className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="font-medium">{title(p.name)}</span>
                    <span className="text-xs text-ink/60">{dateRange(p.start, p.end)}</span>
                  </span>
                  <span className="text-sm text-ink/70">{ENERGY_LABELS[p.energy] ?? p.energy}</span>
                </button>
              </li>
            ))}
          </ol>
          {phase && <Why why={phase.why} ruleIds={phase.rule_ids} />}
        </Card>
      )}

      {phase && (
        <Card className="space-y-4">
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-medium">Daily targets · {title(phase.name)}</h3>
            <Recommended />
          </div>
          {days.length > 1 && (
            <Tabs
              label="Day type"
              options={days.map((d) => ({ id: d, label: DAY_LABELS[d] ?? title(d) }))}
              value={targets[day] ? day : days[0]}
              onChange={onDay}
            />
          )}
          {pending ? (
            <p className="rounded-xl bg-mist p-4 text-sm">{PENDING}</p>
          ) : (
            t && (
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Macro label="Calories" value={`${whole(t.kcal)}`} unit="kcal" />
                <Macro label="Protein" value={whole(t.protein_g)} unit="g" />
                <Macro label="Carbs" value={whole(t.carb_g)} unit="g" />
                <Macro label="Fat" value={whole(t.fat_g)} unit="g" />
              </dl>
            )
          )}
          {!pending && (
            <div className="space-y-1">
              <dl className="text-sm">
                <Fact label="Meals" value={mealPattern(phase.meal_pattern)} />
              </dl>
              <Why why={phase.meal_pattern.why} ruleIds={phase.meal_pattern.rule_ids} />
            </div>
          )}
        </Card>
      )}

      {(pace.rate_pct_bw_week != null || feasibility) && (
        <Card className="space-y-2">
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-medium">Pace</h3>
            <Recommended />
          </div>
          {pending ? (
            <p className="text-sm">{PENDING}</p>
          ) : (
            <dl className="grid gap-2 text-sm sm:grid-cols-3">
              {pace.rate_pct_bw_week != null && (
                <Fact label="Weekly pace" value={`${pace.rate_pct_bw_week}% of body weight`} />
              )}
              {pace.projected_kg_at_event != null && (
                <Fact label="On the day" value={weight(pace.projected_kg_at_event, units)} />
              )}
              {pace.reachable_date && (
                <Fact label="Goal weight by" value={date(pace.reachable_date)} />
              )}
            </dl>
          )}
        </Card>
      )}
    </section>
  );
}

function Macro({ label, value, unit }: { label: string; value: string; unit: string }) {
  return (
    <div className="rounded-xl bg-mist p-3">
      <dt className="text-xs text-ink/60">{label}</dt>
      <dd className="text-xl font-semibold">
        {value} <span className="text-sm font-normal text-ink/60">{unit}</span>
      </dd>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-ink/60">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
