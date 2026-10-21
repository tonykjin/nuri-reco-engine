"use client";

// Placeholder until Task 20 renders the full results screen.

import Link from "next/link";

import { useHydrated } from "@/lib/onboarding/hydration";
import { usePlan } from "@/lib/onboarding/plan";

export function ResultsPlaceholder() {
  const ready = useHydrated(usePlan);
  const { request, response } = usePlan();
  if (!ready) return <div className="h-64" aria-busy="true" />;
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
  return (
    <div className="space-y-4">
      <p className="text-xs uppercase tracking-wide text-ink/60">Status: {response.status}</p>
      <h1 className="text-2xl font-semibold">{response.goal_summary.headline}</h1>
      <p className="text-sm text-ink/70">The full results screen comes in Task 20.</p>
      <details className="rounded-xl bg-white p-4 text-xs">
        <summary className="cursor-pointer text-sm">Request and response JSON</summary>
        <pre className="mt-3 max-h-[60vh] overflow-auto">
          {JSON.stringify({ request, response }, null, 2)}
        </pre>
      </details>
      <Link href="/onboarding/welcome" className="inline-block text-sm text-signal underline">
        Start again
      </Link>
    </div>
  );
}
