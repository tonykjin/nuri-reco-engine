"use client";

import {
  ACTIVITY_OPTIONS,
  DAY_LABELS,
  EXPERIENCE_OPTIONS,
  nextDayType,
  TRAINING_TYPES,
  WEEKDAYS,
} from "@/lib/onboarding/options";
import { useAnswers } from "@/lib/onboarding/store";
import { switchUnits } from "@/lib/onboarding/units";
import { today } from "@/lib/onboarding/validation";

import { ChoiceList, Chips, DateField, Helper, Label, NumberField, Segmented } from "../ui";

export function About() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const metric = answers.units === "metric";
  return (
    <div className="space-y-5">
      <Helper>We use these to estimate how much energy your body uses.</Helper>
      <Segmented
        label="Units"
        options={[
          { id: "metric", label: "Metric" },
          { id: "imperial", label: "Imperial" },
        ]}
        value={answers.units}
        onChange={(u) => update(switchUnits(answers, u))}
      />
      <div className="space-y-1">
        <span className="text-sm text-ink/70">Sex</span>
        <Segmented
          label="Sex"
          options={[
            { id: "female", label: "Female" },
            { id: "male", label: "Male" },
          ]}
          value={answers.sex}
          onChange={(sex) => update({ sex })}
        />
      </div>
      <DateField
        label="Birth date"
        value={answers.birthDate}
        max={today()}
        onChange={(birthDate) => update({ birthDate })}
      />
      <NumberField
        label="Weight"
        unit={metric ? "kg" : "lb"}
        value={answers.weight}
        onChange={(weight) => update({ weight })}
      />
      {metric ? (
        <NumberField
          label="Height"
          unit="cm"
          value={answers.heightCm}
          onChange={(heightCm) => update({ heightCm })}
        />
      ) : (
        <div className="flex gap-3">
          <NumberField
            label="Height"
            unit="ft"
            step={1}
            value={answers.heightFt}
            onChange={(heightFt) => update({ heightFt })}
          />
          <NumberField
            label=" "
            unit="in"
            step={1}
            value={answers.heightIn}
            onChange={(heightIn) => update({ heightIn })}
          />
        </div>
      )}
      <div className="space-y-1">
        <NumberField
          label="Body fat (optional)"
          unit="%"
          value={answers.bodyFatPct}
          onChange={(bodyFatPct) => update({ bodyFatPct })}
        />
        <p className="text-xs text-ink/60">Skip if unsure. We don&apos;t need it.</p>
      </div>
    </div>
  );
}

export function Activity() {
  const activity = useAnswers((s) => s.answers.activity);
  const update = useAnswers((s) => s.update);
  return (
    <div className="space-y-4">
      <Helper>Outside of workouts, how much do you move in a typical day?</Helper>
      <ChoiceList
        options={ACTIVITY_OPTIONS}
        value={activity}
        onChange={(a) => update({ activity: a })}
      />
    </div>
  );
}

const REST_WEEK = ["rest", "rest", "rest", "rest", "rest", "rest", "rest"] as const;

export function Training() {
  const training = useAnswers((s) => s.answers.training);
  const update = useAnswers((s) => s.update);
  const set = (patch: Partial<typeof training>) => update({ training: { ...training, ...patch } });
  const trains = training.type !== "none";
  const lifts = training.type === "lifting" || training.type === "mixed";

  return (
    <div className="space-y-6">
      <Helper>Harder and longer days get more fuel.</Helper>
      <ChoiceList
        options={TRAINING_TYPES}
        value={training.type}
        onChange={(type) =>
          type === "none"
            ? set({
                type,
                daysPerWeek: 0,
                schedule: [...REST_WEEK],
                experience: null,
              })
            : set({
                type,
                experience: type === "running" ? null : training.experience,
              })
        }
      />
      {trains && (
        <>
          <section className="space-y-2">
            <Label>Days per week</Label>
            <Chips
              options={[1, 2, 3, 4, 5, 6, 7].map((n) => ({
                id: String(n),
                label: String(n),
              }))}
              values={training.daysPerWeek ? [String(training.daysPerWeek)] : []}
              onToggle={(id) => set({ daysPerWeek: Number(id) })}
            />
          </section>
          <section className="space-y-2">
            <Label>Your week</Label>
            <p className="text-xs text-ink/60">Tap a day to change it: rest, easy, hard, long.</p>
            <div className="grid grid-cols-7 gap-1.5">
              {training.schedule.map((day, i) => (
                <button
                  key={WEEKDAYS[i]}
                  type="button"
                  aria-label={`${WEEKDAYS[i]}: ${DAY_LABELS[day] ?? day}`}
                  onClick={() =>
                    set({
                      schedule: training.schedule.map((d, j) => (j === i ? nextDayType(d) : d)),
                    })
                  }
                  className={`flex min-h-16 flex-col items-center justify-center rounded-xl text-xs ${
                    day === "rest"
                      ? "bg-white text-ink/60"
                      : day === "easy"
                        ? "bg-ink/15"
                        : day === "quality"
                          ? "bg-signal/80 text-white"
                          : "bg-ink text-white"
                  }`}
                >
                  <span className="font-medium">{WEEKDAYS[i]}</span>
                  <span>{DAY_LABELS[day] ?? day}</span>
                </button>
              ))}
            </div>
          </section>
          {lifts && (
            <section className="space-y-2">
              <Label>How long have you been lifting? (optional)</Label>
              <Chips
                options={EXPERIENCE_OPTIONS}
                values={training.experience ? [training.experience] : []}
                onToggle={(id) => set({ experience: training.experience === id ? null : id })}
              />
            </section>
          )}
        </>
      )}
    </div>
  );
}
