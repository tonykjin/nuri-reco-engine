"use client";

import {
  type Answers,
  GOAL_CHOICES,
  GOAL_LABELS,
  type GoalDetail,
  type GoalType,
  goalTypes,
  MAX_GOALS,
  rankedGoalTypes,
} from "@/lib/onboarding/answers";
import { DISTANCES, EVENT_TYPES, OCCASIONS } from "@/lib/onboarding/options";
import { usePlan } from "@/lib/onboarding/plan";
import { useAnswers } from "@/lib/onboarding/store";
import { today } from "@/lib/onboarding/validation";

import { Choice, Chips, DateField, Helper, Label, toggle } from "../ui";

export function Goals() {
  const goals = useAnswers((s) => s.answers.goals);
  const update = useAnswers((s) => s.update);
  return (
    <div className="space-y-4">
      <Helper>Pick up to {MAX_GOALS}. You&apos;ll rank them next.</Helper>
      <Chips
        options={GOAL_CHOICES}
        values={goals}
        max={MAX_GOALS}
        onToggle={(id) =>
          update({
            goals: toggle(goals, id),
            ranking: [],
            sequenceConfirmed: false,
          })
        }
      />
    </div>
  );
}

export function Priority() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const response = usePlan((s) => s.response);
  const ranked = rankedGoalTypes(answers);
  const askedToOrder = response?.status === "needs_ordering";

  const move = (i: number, by: number) => {
    const next = [...ranked];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    update({ ranking: next });
  };

  return (
    <div className="space-y-4">
      <Helper>Your top goal sets your calories. The others fit around it.</Helper>
      <ol className="space-y-2">
        {ranked.map((type, i) => (
          <li key={type} className="flex min-h-14 items-center gap-3 rounded-xl bg-white px-4">
            <span className="flex size-7 items-center justify-center rounded-full bg-mist text-sm">
              {i + 1}
            </span>
            <span className="flex-1 font-medium">{GOAL_LABELS[type]}</span>
            <button
              type="button"
              aria-label={`Move ${GOAL_LABELS[type]} up`}
              disabled={i === 0}
              className="size-11 rounded-lg text-lg hover:bg-mist disabled:opacity-25"
              onClick={() => move(i, -1)}
            >
              ↑
            </button>
            <button
              type="button"
              aria-label={`Move ${GOAL_LABELS[type]} down`}
              disabled={i === ranked.length - 1}
              className="size-11 rounded-lg text-lg hover:bg-mist disabled:opacity-25"
              onClick={() => move(i, 1)}
            >
              ↓
            </button>
          </li>
        ))}
      </ol>
      {askedToOrder && (
        <div className="space-y-3 rounded-xl border-2 border-signal/40 bg-white p-4">
          <p className="text-sm">{response.goal_summary.goals[0]?.why}</p>
          <Choice
            selected={answers.sequenceConfirmed === true}
            onClick={() => update({ sequenceConfirmed: !answers.sequenceConfirmed })}
            label="Do them one after another, in this order"
          />
        </div>
      )}
    </div>
  );
}

function setDetail(
  update: (patch: Partial<Answers>) => void,
  answers: Answers,
  type: GoalType,
  patch: GoalDetail,
) {
  update({
    goalDetails: {
      ...answers.goalDetails,
      [type]: { ...answers.goalDetails[type], ...patch },
    },
  });
}

function Occasion() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const d = answers.goalDetails.deadline_event ?? {};
  const set = (patch: GoalDetail) => setDetail(update, answers, "deadline_event", patch);
  return (
    <section className="space-y-3">
      <Label>What&apos;s the occasion?</Label>
      <Chips
        options={OCCASIONS}
        values={d.event ? [d.event] : []}
        onToggle={(id) => set({ event: d.event === id ? null : id })}
      />
      <DateField
        label="Date"
        value={d.eventDate}
        min={today()}
        onChange={(v) => set({ eventDate: v })}
      />
    </section>
  );
}

function Race() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const d = answers.goalDetails.endurance_event ?? {};
  const set = (patch: GoalDetail) => setDetail(update, answers, "endurance_event", patch);
  return (
    <section className="space-y-3">
      <Label>What are you training for?</Label>
      <Chips
        options={EVENT_TYPES}
        values={d.eventType ? [d.eventType] : []}
        onToggle={(id) =>
          set({
            eventType: d.eventType === id ? null : id,
            distance: id === "running" ? d.distance : null,
          })
        }
      />
      {d.eventType === "running" && (
        <>
          <Label>Distance</Label>
          <Chips
            options={DISTANCES}
            values={d.distance ? [d.distance] : []}
            onToggle={(id) => set({ distance: d.distance === id ? null : id })}
          />
        </>
      )}
      <DateField
        label="Event date"
        value={d.eventDate}
        min={today()}
        onChange={(v) => set({ eventDate: v })}
      />
    </section>
  );
}

// Event goals only; the target weight has its own screen after the health check (spec §11.3).
export function GoalDetails() {
  const answers = useAnswers((s) => s.answers);
  const types = goalTypes(answers.goals);
  return (
    <div className="space-y-8">
      <Helper>The date helps us plan a pace that fits.</Helper>
      {types.includes("deadline_event") && <Occasion />}
      {types.includes("endurance_event") && <Race />}
    </div>
  );
}
