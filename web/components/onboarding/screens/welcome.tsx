"use client";

import { useRouter } from "next/navigation";

import { PERSONAS } from "@/lib/onboarding/personas";
import { usePlan } from "@/lib/onboarding/plan";
import { useAnswers } from "@/lib/onboarding/store";

import { Helper } from "../ui";

export function Welcome() {
  const router = useRouter();
  const firstName = useAnswers((s) => s.answers.firstName);
  const update = useAnswers((s) => s.update);
  const replace = useAnswers((s) => s.replace);
  const clearPlan = usePlan((s) => s.clear);

  const prefill = (name: string, then: "step" | "results") => {
    replace(PERSONAS[name].answers);
    clearPlan();
    router.push(then === "results" ? "/onboarding/building" : "/onboarding/goals");
  };

  return (
    <div className="space-y-8">
      <div className="space-y-3">
        <Helper>A few quick questions, then we&apos;ll show you the plan we set and why.</Helper>
        <label className="block space-y-1">
          <span className="text-sm text-ink/70">What should we call you?</span>
          <input
            className="min-h-14 w-full rounded-xl bg-white px-4 text-lg"
            value={firstName}
            autoComplete="given-name"
            onChange={(e) => update({ firstName: e.target.value })}
            placeholder="First name"
          />
        </label>
      </div>

      <details className="rounded-xl bg-white/60 p-4 text-sm">
        <summary className="cursor-pointer text-ink/70">Prefill as persona…</summary>
        <ul className="mt-3 divide-y divide-ink/10">
          {Object.keys(PERSONAS).map((name) => (
            <li key={name} className="flex items-center justify-between gap-2 py-2">
              <span className="capitalize">{name.replaceAll("_", " ")}</span>
              <span className="flex gap-2">
                <button
                  type="button"
                  className="rounded-full bg-white px-3 py-1.5 hover:bg-mist"
                  onClick={() => prefill(name, "step")}
                >
                  Step through
                </button>
                <button
                  type="button"
                  className="rounded-full bg-ink px-3 py-1.5 text-white"
                  onClick={() => prefill(name, "results")}
                >
                  Jump to results
                </button>
              </span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}
