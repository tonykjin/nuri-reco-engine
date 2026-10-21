"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { useHydrated } from "@/lib/onboarding/hydration";
import { usePlan } from "@/lib/onboarding/plan";
import { nextStep, previousStep, stepById, visibleSteps } from "@/lib/onboarding/steps";
import { useAnswers } from "@/lib/onboarding/store";

import { StepNav } from "./nav";

export function OnboardingFlow({ stepId }: { stepId: string }) {
  const router = useRouter();
  const answersReady = useHydrated(useAnswers);
  const planReady = useHydrated(usePlan);
  const hydrated = answersReady && planReady;
  const answers = useAnswers((s) => s.answers);
  const step = stepById(stepId);
  const shown = hydrated && step !== undefined && step.condition(answers);

  // A step whose condition is false (e.g. a bookmarked one) forwards to the next one that applies.
  useEffect(() => {
    if (hydrated && step && !step.condition(answers)) {
      const next = nextStep(step.id, answers);
      if (next) router.replace(`/onboarding/${next.id}`);
    }
  }, [hydrated, step, answers, router]);

  if (!step || !shown) {
    return <div className="h-64" aria-busy="true" />;
  }

  const steps = visibleSteps(answers);
  const position = steps.findIndex((s) => s.id === step.id) + 1;
  const back = previousStep(step.id, answers);
  const next = nextStep(step.id, answers);
  const complete = step.complete?.(answers) ?? true;
  const Screen = step.component;

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <div
          className="h-1.5 w-full overflow-hidden rounded-full bg-white"
          role="progressbar"
          aria-valuemin={1}
          aria-valuemax={steps.length}
          aria-valuenow={position}
          aria-label={`Step ${position} of ${steps.length}`}
        >
          <div
            className="h-full rounded-full bg-signal transition-all"
            style={{ width: `${(position / steps.length) * 100}%` }}
          />
        </div>
        <p className="text-xs text-ink/60">
          Step {position} of {steps.length}
        </p>
      </div>

      <h1 className="text-2xl font-semibold">{step.title}</h1>
      <StepNav value={{ next: () => next && router.push(`/onboarding/${next.id}`) }}>
        <Screen />
      </StepNav>

      <div className="flex justify-between gap-3">
        <button
          type="button"
          className="rounded-full px-5 py-2.5 text-sm text-ink/70 hover:text-ink disabled:invisible"
          disabled={!back}
          onClick={() => back && router.push(`/onboarding/${back.id}`)}
        >
          Back
        </button>
        {next && (
          <button
            type="button"
            className="rounded-full bg-signal px-6 py-2.5 text-sm font-medium text-white disabled:opacity-40"
            disabled={!complete}
            onClick={() => router.push(`/onboarding/${next.id}`)}
          >
            Continue
          </button>
        )}
      </div>
    </div>
  );
}
