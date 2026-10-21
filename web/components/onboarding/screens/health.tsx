"use client";

// TODO(RD-review): all copy on this screen (helper text, "why we ask", option and SCOFF wording)
// needs a registered dietitian's review before real users see it.

import { useState } from "react";

import { CONDITIONS, MEDICATIONS, PREGNANCY_OPTIONS, SCOFF_ITEMS } from "@/lib/onboarding/options";
import { useAnswers } from "@/lib/onboarding/store";

import { Chip, Chips, ChoiceList, Helper, Label, toggle, YesNo } from "../ui";

export function Health() {
  const answers = useAnswers((s) => s.answers);
  const update = useAnswers((s) => s.update);
  const health = answers.health;
  const set = (patch: Partial<typeof health>) => update({ health: { ...health, ...patch } });
  const [kidney, setKidney] = useState(health.ckdStage !== null);

  return (
    <div className="space-y-7">
      <Helper>
        A few health questions help us keep your plan safe. Answer what you&apos;re comfortable
        with.
      </Helper>

      <details className="rounded-xl bg-white/70 p-4 text-sm">
        <summary className="cursor-pointer font-medium">Why we ask</summary>
        <p className="mt-2 text-ink/70">
          Some situations, like pregnancy, kidney disease or certain medicines, change what a safe
          plan looks like. When they apply, we keep things gentle and suggest checking in with a
          registered dietitian or your doctor. Your answers stay on this device for this demo.
        </p>
      </details>

      {answers.sex === "female" && (
        <section className="space-y-2">
          <Label>Are you pregnant or breastfeeding?</Label>
          <ChoiceList
            options={PREGNANCY_OPTIONS}
            value={health.pregnancy}
            onChange={(pregnancy) => set({ pregnancy })}
          />
        </section>
      )}

      <section className="space-y-2">
        <Label>Any of these conditions?</Label>
        <div className="flex flex-wrap gap-2">
          {CONDITIONS.map((c) => (
            <Chip
              key={c.id}
              selected={health.conditions.includes(c.id)}
              onClick={() => set({ conditions: toggle(health.conditions, c.id) })}
            >
              {c.label}
            </Chip>
          ))}
          <Chip
            selected={kidney}
            onClick={() => {
              setKidney(!kidney);
              set({ ckdStage: null });
            }}
          >
            Kidney disease
          </Chip>
        </div>
        {kidney && (
          <div className="space-y-2 pt-2">
            <p className="text-sm text-ink/70">Which stage? Your doctor will know.</p>
            <Chips
              options={[1, 2, 3, 4, 5].map((n) => ({
                id: String(n),
                label: `Stage ${n}`,
              }))}
              values={health.ckdStage ? [String(health.ckdStage)] : []}
              onToggle={(id) => set({ ckdStage: Number(id) })}
            />
          </div>
        )}
      </section>

      <section className="space-y-2">
        <Label>Do you take any of these?</Label>
        <Chips
          options={MEDICATIONS}
          values={health.medications}
          onToggle={(id) => set({ medications: toggle(health.medications, id) })}
        />
      </section>

      <section className="space-y-3">
        <Label>About eating</Label>
        <p className="text-sm text-ink/70">
          Five yes/no questions many clinics use. There are no right answers.
        </p>
        {SCOFF_ITEMS.map((item, i) => (
          <YesNo
            key={item}
            label={item}
            disabled={health.scoffDeclined}
            value={health.scoff[i] ?? null}
            onChange={(v) => set({ scoff: health.scoff.map((x, j) => (j === i ? v : x)) })}
          />
        ))}
        <Chip
          selected={health.scoffDeclined === true}
          onClick={() => set({ scoffDeclined: !health.scoffDeclined })}
        >
          Prefer not to say
        </Chip>
      </section>
    </div>
  );
}
