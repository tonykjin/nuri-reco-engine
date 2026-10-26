"use client";

// Results screen (spec §11.3): renders PlanResponse fields only. Blocked plans show no numbers;
// rd_review plans show "Pending your dietitian" in place of targets.

import Link from "next/link";
import { useState } from "react";

import { useHydrated } from "@/lib/onboarding/hydration";
import { usePlan } from "@/lib/onboarding/plan";
import { useAnswers } from "@/lib/onboarding/store";
import { byDayOrder, date, referralTitle, weight } from "@/lib/results/format";

import { Banner, Why } from "./common";
import { DevDrawer } from "./DevDrawer";
import { GoalsPanel } from "./GoalsPanel";
import { SampleDayCard } from "./SampleDayCard";
import { ScorePanel } from "./ScorePanel";

export function Results() {
  const planReady = useHydrated(usePlan);
  const answersReady = useHydrated(useAnswers);
  const { request, response } = usePlan();
  const units = useAnswers((s) => s.answers.units);
  const [phaseName, setPhaseName] = useState<string | null>(null);
  const [day, setDay] = useState("rest");

  if (!planReady || !answersReady) return <div className="h-64" aria-busy="true" />;
  if (!response) {
    return (
      <div className="space-y-4">
        <p>No plan yet.</p>
        <Link href="/onboarding" className="text-signal underline">
          Start onboarding
        </Link>
      </div>
    );
  }

  const { status, safety, goal_summary: summary, feasibility } = response;
  const phases = response.phases ?? [];
  const byPhase = response.loam_score_profile.by_phase;
  const selected = phaseName ?? phases[0]?.name ?? byPhase[0]?.phase;
  const phase = phases.find((p) => p.name === selected) ?? phases[0];
  const profile = byPhase.find((b) => b.phase === selected) ?? byPhase[0];
  const blocked = status === "blocked";
  const pending = status === "rd_review";
  const warnings = safety?.warnings ?? [];
  const referrals = safety?.referrals ?? [];
  // The day type the targets card shows: the selected one if this phase has it.
  const dayTypes = Object.keys(phase?.targets_by_day_type ?? {}).sort(byDayOrder);
  const shownDay = dayTypes.includes(day) ? day : dayTypes[0];

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <p className="text-xs tracking-wide text-ink/60 uppercase">Your plan</p>
        <h1 className="text-2xl leading-snug font-semibold">{summary.headline}</h1>
      </header>

      {blocked && (
        <Banner tone="hold" title="We've paused the numbers for now">
          {(safety?.blocks ?? []).map((b) => (
            <div key={b.rule_id} className="space-y-1 text-sm">
              <p>{b.message}</p>
              <Why why={b.why} ruleIds={b.rule_ids} />
            </div>
          ))}
        </Banner>
      )}

      {pending && (
        <Banner tone="review" title="A dietitian will review your plan">
          {warnings.map((w) => (
            <div key={w.rule_id} className="space-y-1 text-sm">
              <p>{w.message}</p>
              <Why why={w.why} ruleIds={w.rule_ids} />
            </div>
          ))}
          <p className="text-sm text-ink/70">
            Your score weights are below. Targets show as &quot;Pending your dietitian&quot; until
            they&apos;re confirmed.
          </p>
        </Banner>
      )}

      {status === "clamped" && feasibility && (
        <Banner tone="notice" title="Your full goal takes a little longer than your date">
          <p className="text-sm text-ink/80">
            {feasibility.projected_kg_at_event != null &&
              `About ${weight(feasibility.projected_kg_at_event, units)} on the day. `}
            {feasibility.reachable_date &&
              `Your goal weight by ${date(feasibility.reachable_date)}, at a pace that's safe.`}
          </p>
        </Banner>
      )}

      {((!pending && warnings.length > 0) || referrals.length > 0) && (
        <div className="space-y-3">
          {(pending ? [] : warnings).map((w) => (
            <Banner key={w.rule_id} tone="notice" title={w.message}>
              <Why why={w.why} ruleIds={w.rule_ids} />
            </Banner>
          ))}
          {referrals.map((r) => (
            <Banner key={r.rule_id} tone={blocked ? "hold" : "notice"} title={referralTitle(r.to)}>
              <p className="text-sm text-ink/80">{r.message}</p>
            </Banner>
          ))}
        </div>
      )}

      <GoalsPanel
        response={response}
        phase={blocked ? undefined : phase}
        onPhase={setPhaseName}
        day={day}
        onDay={setDay}
        pending={pending}
        units={units}
      />

      {!blocked && (
        <ScorePanel
          response={response}
          profile={profile}
          onPhase={setPhaseName}
          day={day}
          onDay={setDay}
          pending={pending}
        />
      )}

      {!blocked && status !== "needs_ordering" && request && phase && shownDay && (
        <SampleDayCard request={request} phase={phase.name} day={shownDay} pending={pending} />
      )}

      <DevDrawer request={request} response={response} />

      <Link href="/onboarding/welcome" className="inline-block text-sm text-signal underline">
        Start again
      </Link>
    </div>
  );
}
