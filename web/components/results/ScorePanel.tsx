"use client";

import {
  APPLIES_LABELS,
  byDayOrder,
  COMPONENT_LABELS,
  DAY_LABELS,
  DISABLED_LABELS,
  DISABLED_REASONS,
  MICRO_LABELS,
  num,
  type PhaseScoreProfile,
  type PlanResponse,
  type ScoreComponent,
  target,
  title,
  unit,
  WEIGHT_LABELS,
  date,
} from "@/lib/results/format";

import { Card, PENDING, Recommended, Tabs, Why } from "./common";

interface Props {
  response: PlanResponse;
  profile: PhaseScoreProfile | undefined;
  onPhase: (name: string) => void;
  day: string;
  onDay: (day: string) => void;
  pending: boolean;
}

/** Components for the selected day type, plus those that apply to every day. */
function forDay(components: ScoreComponent[], day: string | undefined): ScoreComponent[] {
  return components.filter((c) => c.day_type == null || c.day_type === day);
}

export function ScorePanel({ response, profile, onPhase, day, onDay, pending }: Props) {
  const lsp = response.loam_score_profile;
  const byPhase = lsp.by_phase;
  if (!profile) return null;

  const starts = new Map((response.phases ?? []).map((p) => [p.name, p.start]));
  const dayTypes = (
    [...new Set(profile.components.map((c) => c.day_type).filter(Boolean))] as string[]
  ).sort(byDayOrder);
  const selectedDay = dayTypes.includes(day) ? day : dayTypes[0];
  const components = forDay(profile.components, selectedDay);
  const order = Object.keys(profile.weights);

  return (
    <section aria-labelledby="score-heading" className="space-y-4">
      <div className="flex items-center justify-between gap-2">
        <h2 id="score-heading" className="text-xl font-semibold">
          What affects your Loam Score
        </h2>
        <Recommended />
      </div>

      {byPhase.length > 1 && (
        <Tabs
          label="Phase"
          options={byPhase.map((b) => ({
            id: b.phase,
            label: title(b.phase),
            hint: starts.get(b.phase) ? date(starts.get(b.phase)) : undefined,
          }))}
          value={profile.phase}
          onChange={onPhase}
        />
      )}

      <Card className="space-y-5">
        <p className="text-sm text-ink/70">
          How much each part counts toward your score
          {byPhase.length > 1 ? ` in your ${title(profile.phase).toLowerCase()} phase` : ""}.
        </p>
        {dayTypes.length > 1 && !pending && (
          <Tabs
            label="Day type for targets"
            options={dayTypes.map((d) => ({ id: d, label: DAY_LABELS[d] ?? title(d) }))}
            value={selectedDay}
            onChange={onDay}
          />
        )}
        <ul className="space-y-5">
          {order.map((key) => {
            const w = profile.weights[key];
            const items = components.filter((c) => c.weight_key === key);
            return (
              <li key={key} className="space-y-1.5">
                <div className="flex items-baseline justify-between text-sm">
                  <span className="font-medium">{WEIGHT_LABELS[key] ?? title(key)}</span>
                  <span className="tabular-nums">{w}%</span>
                </div>
                <div
                  className="h-2.5 overflow-hidden rounded-full bg-mist"
                  role="meter"
                  aria-label={`${WEIGHT_LABELS[key] ?? key} weight`}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={w}
                >
                  <div className="h-full rounded-full bg-signal" style={{ width: `${w}%` }} />
                </div>
                {key === "micro" ? (
                  <Micros profile={profile} pending={pending} />
                ) : (
                  items.map((c) => (
                    <div key={c.id + (c.day_type ?? "")} className="text-sm text-ink/80">
                      <span>
                        {COMPONENT_LABELS[c.id] ?? title(c.id)}:{" "}
                        {pending ? PENDING : target(c.target)}
                      </span>
                      <Applies c={c} />
                      <Why why={c.why} ruleIds={c.rule_ids} />
                    </div>
                  ))
                )}
              </li>
            );
          })}
        </ul>
        <p className="text-xs text-ink/50">
          Weights add up to 100. Tags show what each target is scored on: a meal, a day or the week.
        </p>
      </Card>

      {(profile.disabled ?? []).length > 0 && (
        <Card className="space-y-2">
          <h3 className="font-medium">Not counted / handled by your dietitian</h3>
          <ul className="list-disc pl-5 text-sm text-ink/80">
            {(profile.disabled ?? []).map((d) => (
              <li key={d.id}>
                {DISABLED_LABELS[d.id] ?? title(d.id)}
                {DISABLED_REASONS[d.reason] ? `: ${DISABLED_REASONS[d.reason]}` : ""}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {(lsp.top_levers ?? []).length > 0 && (
        <Card className="space-y-2">
          <h3 className="font-medium">Your top levers</h3>
          {pending ? (
            <p className="text-sm">{PENDING}</p>
          ) : (
            <ol className="list-decimal space-y-1 pl-5 text-sm">
              {(lsp.top_levers ?? []).map((l) => (
                <li key={l.component}>{l.text}</li>
              ))}
            </ol>
          )}
        </Card>
      )}
    </section>
  );
}

function Applies({ c }: { c: ScoreComponent }) {
  return (
    <span className="ml-2 inline-flex gap-1 align-middle">
      {c.applies_to.map((a) => (
        <span
          key={a}
          className="rounded bg-mist px-1.5 text-[10px] tracking-wide text-ink/60 uppercase"
        >
          {APPLIES_LABELS[a] ?? a}
        </span>
      ))}
    </span>
  );
}

function Micros({ profile, pending }: { profile: PhaseScoreProfile; pending: boolean }) {
  const micros = profile.micronutrients ?? [];
  if (micros.length === 0) return null;
  return (
    <ul className="grid grid-cols-2 gap-x-4 gap-y-1 pt-1 text-sm text-ink/80">
      {micros.map((m) => (
        <li key={m.id} className="flex justify-between gap-2">
          <span>{MICRO_LABELS[m.id] ?? title(m.id)}</span>
          <span className="tabular-nums">
            {pending ? "pending" : `${num(m.target)} ${unit(m.unit)}`}
          </span>
        </li>
      ))}
      <li className="col-span-2 text-xs text-ink/50">
        Daily amounts, averaged over {micros[0].window.replace("d", " days")}.
      </li>
    </ul>
  );
}
