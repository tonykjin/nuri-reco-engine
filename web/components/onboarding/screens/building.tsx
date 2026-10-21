"use client";

// Building your plan: POST /v1/plan, then /results (any status; needs_ordering goes back to ranking).

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { mapAnswers } from "@/lib/onboarding/mapAnswers";
import { fetchPlan, usePlan } from "@/lib/onboarding/plan";
import { useAnswers } from "@/lib/onboarding/store";
import { today } from "@/lib/onboarding/validation";

const STAGES = [
  "Checking safety",
  "Setting your goals",
  "Working out your targets",
  "Building your score",
];
const TICK_MS = 450;

export function Building() {
  const router = useRouter();
  const answers = useAnswers((s) => s.answers);
  const save = usePlan((s) => s.save);
  const [stage, setStage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const started = useRef(-1);
  // Mapping fails only if an earlier answer is missing (e.g. a bookmarked URL).
  const mapped = useMemo(() => {
    try {
      return { request: mapAnswers(answers, { asOf: today() }), missing: null };
    } catch (e) {
      return { request: null, missing: (e as Error).message };
    }
  }, [answers]);

  useEffect(() => {
    const t = setInterval(() => setStage((s) => Math.min(s + 1, STAGES.length - 1)), TICK_MS);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    const { request } = mapped;
    if (!request || started.current === attempt) return; // strict mode runs effects twice in dev
    started.current = attempt;
    const minWait = new Promise((r) => setTimeout(r, STAGES.length * TICK_MS));
    Promise.all([fetchPlan(request), minWait])
      .then(([response]) => {
        save(request, response);
        router.replace(response.status === "needs_ordering" ? "/onboarding/priority" : "/results");
      })
      .catch((e: Error) => setError(e.message));
  }, [attempt, mapped, router, save]);

  if (mapped.missing) {
    return <p className="text-sm text-signal">Some answers are missing ({mapped.missing}).</p>;
  }
  if (error) {
    return (
      <div className="space-y-4">
        <p className="text-sm text-signal">We couldn&apos;t build your plan: {error}</p>
        <button
          type="button"
          className="rounded-full bg-signal px-6 py-2.5 text-sm font-medium text-white"
          onClick={() => {
            setError(null);
            setAttempt((a) => a + 1);
          }}
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <ol className="space-y-3" aria-live="polite">
      {STAGES.map((s, i) => (
        <li key={s} className="flex items-center gap-3 rounded-xl bg-white px-4 py-3">
          <span
            className={`size-3 rounded-full ${i < stage ? "bg-ink" : i === stage ? "animate-pulse bg-signal" : "bg-mist"}`}
          />
          <span className={i <= stage ? "" : "text-ink/40"}>{s}</span>
        </li>
      ))}
    </ol>
  );
}
