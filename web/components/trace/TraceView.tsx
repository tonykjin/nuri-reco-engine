"use client";

// Decision trace (Task 22): POST /v1/plan/trace rendered as a collapsible tree for dietitian
// review. Renders API fields only; the engine records the stages, rules and their details.

import Link from "next/link";
import { type ReactNode, useEffect, useMemo, useState } from "react";

import { Card } from "@/components/results/common";
import { useHydrated } from "@/lib/onboarding/hydration";
import { mapAnswers, type PlanRequest } from "@/lib/onboarding/mapAnswers";
import { PERSONAS } from "@/lib/onboarding/personas";
import { usePlan } from "@/lib/onboarding/plan";
import {
  fetchTrace,
  stageLabel,
  stageRuleIds,
  type TracedPlan,
  type TraceRule,
  type TraceStage,
} from "@/lib/trace/trace";

const MINE = "__mine__";

// The last answer, for the source it was fetched for; any other key is loading.
type Result =
  | { key: string; kind: "error"; message: string }
  | { key: string; kind: "ready"; traced: TracedPlan };

export function TraceView() {
  const planReady = useHydrated(usePlan);
  const mine = usePlan((s) => s.request);
  const [source, setSource] = useState("maya");
  const [simulate, setSimulate] = useState(false);
  const [result, setResult] = useState<Result | null>(null);

  const request = useMemo<PlanRequest | null>(() => {
    if (source === MINE) return mine;
    const persona = PERSONAS[source];
    return persona ? mapAnswers(persona.answers, { asOf: persona.as_of }) : null;
  }, [source, mine]);

  const key = `${source}/${simulate}`;
  const state = result?.key === key ? result : { kind: "loading" as const };

  useEffect(() => {
    if (!request) return;
    const controller = new AbortController();
    fetchTrace(request, simulate, controller.signal)
      .then((traced) => setResult({ key, kind: "ready", traced }))
      .catch((e: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ key, kind: "error", message: e instanceof Error ? e.message : String(e) });
        }
      });
    return () => controller.abort();
  }, [request, simulate, key]);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Decision trace</h1>
        <p className="text-sm text-ink/70">
          Every engine stage in order and every rule it fired, for dietitian review.{" "}
          <Link href="/results" className="text-signal underline">
            Back to results
          </Link>
        </p>
      </header>

      <Card className="flex flex-wrap items-end gap-4">
        <label className="space-y-1 text-sm">
          <span className="block text-ink/60">Request</span>
          <select
            className="rounded-xl border border-ink/20 bg-white px-3 py-2"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            {planReady && mine && <option value={MINE}>Your latest plan</option>}
            {Object.keys(PERSONAS).map((name) => (
              <option key={name} value={name}>
                {name.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={simulate}
            onChange={(e) => setSimulate(e.target.checked)}
          />
          Add simulated weeks of logs (demo data)
        </label>
      </Card>

      {!request ? (
        <p className="text-sm text-ink/70">No request to trace.</p>
      ) : state.kind === "loading" ? (
        <div className="h-64 animate-pulse rounded-2xl bg-mist" aria-busy="true" />
      ) : state.kind === "error" ? (
        <p className="text-sm text-ink/70">{state.message}</p>
      ) : (
        <TraceBody traced={state.traced} />
      )}
    </div>
  );
}

function TraceBody({ traced }: { traced: TracedPlan }) {
  const { trace, plan } = traced;
  return (
    <div className="space-y-6">
      <p className="text-sm">
        Status <span className="font-mono">{plan.status}</span> · {trace.stages.length} stages ·{" "}
        {trace.rules_fired.length} rules fired
      </p>

      <ol className="space-y-3">
        {trace.stages.map((stage, i) => (
          <li key={`${stage.stage}-${i}`}>
            <StageNode stage={stage} index={i + 1} rules={trace.rules} />
          </li>
        ))}
      </ol>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold">All rules fired, in order</h2>
        <ol className="space-y-1">
          {trace.rules_fired.map((id, i) => (
            <li key={id} className="flex gap-2">
              <span className="w-8 shrink-0 text-right text-xs text-ink/40 tabular-nums">
                {i + 1}
              </span>
              <RuleNode id={id} rule={trace.rules[id]} />
            </li>
          ))}
        </ol>
      </section>

      <details className="rounded-2xl bg-white p-4">
        <summary className="cursor-pointer text-sm font-medium select-none">Raw trace JSON</summary>
        <Json value={traced} />
      </details>
    </div>
  );
}

function StageNode({
  stage,
  index,
  rules,
  child = false,
}: {
  stage: TraceStage;
  index?: number;
  rules: Record<string, TraceRule>;
  child?: boolean;
}) {
  const count = stageRuleIds(stage).length;
  const ruleIds = stage.rule_ids ?? [];
  return (
    <details className={`rounded-2xl bg-white p-4 ${child ? "border border-ink/10" : ""}`}>
      <summary className="flex cursor-pointer items-baseline justify-between gap-3 select-none">
        <span className="font-medium">
          {index !== undefined && <span className="mr-2 text-ink/40 tabular-nums">{index}.</span>}
          {stageLabel(stage, child)}
        </span>
        <span className="shrink-0 text-xs text-ink/60">
          {count} {count === 1 ? "rule" : "rules"}
        </span>
      </summary>
      <div className="mt-3 space-y-3">
        {ruleIds.length > 0 && (
          <ul className="space-y-1">
            {ruleIds.map((id) => (
              <li key={id}>
                <RuleNode id={id} rule={rules[id]} />
              </li>
            ))}
          </ul>
        )}
        {(stage.children ?? []).map((c, i) => (
          <StageNode key={`${c.stage}-${i}`} stage={c} rules={rules} child />
        ))}
        <JsonToggle label="Inputs" value={stage.inputs} />
        <JsonToggle label="Outputs" value={stage.outputs} />
      </div>
    </details>
  );
}

function RuleNode({ id, rule }: { id: string; rule?: TraceRule }) {
  return (
    <details className="w-full text-sm">
      <summary className="cursor-pointer select-none">
        <span className="font-mono text-xs">{id}</span>
        {rule?.verify && (
          <span className="ml-2 rounded-full bg-signal/10 px-2 py-0.5 text-[11px]">⚠️ verify</span>
        )}
        {rule?.heuristic && (
          <span className="ml-2 rounded-full bg-mist px-2 py-0.5 text-[11px]">🧪 heuristic</span>
        )}
      </summary>
      {rule ? (
        <dl className="mt-2 space-y-2 rounded-xl bg-mist p-3">
          {rule.text && <Field label="Rule">{rule.text}</Field>}
          {rule.why && <Field label="Shown to users">{rule.why}</Field>}
          <Field label="Source">
            <span className="font-mono text-xs">knowledge/{rule.file}.yaml</span>
          </Field>
          {(rule.citations ?? []).length > 0 && (
            <Field label="Citations">
              <ul className="space-y-0.5">
                {(rule.citations ?? []).map((c) => (
                  <li key={c.id}>
                    {c.url ? (
                      <a
                        href={c.url}
                        className="text-signal underline"
                        target="_blank"
                        rel="noreferrer"
                      >
                        {c.label}
                      </a>
                    ) : (
                      c.label
                    )}
                  </li>
                ))}
              </ul>
            </Field>
          )}
        </dl>
      ) : (
        <p className="mt-2 text-ink/60">No details for this rule.</p>
      )}
    </details>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-ink/60">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function JsonToggle({ label, value }: { label: string; value: unknown }) {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-ink/60 select-none hover:text-ink">{label}</summary>
      <Json value={value} />
    </details>
  );
}

function Json({ value }: { value: unknown }) {
  return (
    <pre className="mt-2 max-h-96 overflow-auto rounded-xl bg-ink p-3 text-[11px] leading-relaxed text-white">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
