"use client";

import { useState } from "react";

import { ruleIds } from "@/lib/results/format";

function CopyBlock({ label, value }: { label: string; value: unknown }) {
  const [copied, setCopied] = useState(false);
  const text = JSON.stringify(value, null, 2);
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium">{label}</h4>
        <button
          type="button"
          className="rounded-full bg-mist px-3 py-1 text-xs hover:bg-ink hover:text-white"
          onClick={async () => {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="max-h-96 overflow-auto rounded-xl bg-ink p-3 text-[11px] leading-relaxed text-white">
        {text}
      </pre>
    </div>
  );
}

export function DevDrawer({ request, response }: { request: unknown; response: unknown }) {
  const ids = ruleIds(response);
  return (
    <details className="rounded-2xl border border-ink/10 bg-white/60 p-4">
      <summary className="cursor-pointer text-sm font-medium">Developer drawer</summary>
      <div className="mt-4 space-y-5">
        <p className="text-sm text-ink/70">
          One <code>POST /v1/plan</code> call: this request in, this response out.
        </p>
        <CopyBlock label="PlanRequest" value={request} />
        <CopyBlock label="PlanResponse" value={response} />
        <div className="space-y-2">
          <h4 className="text-sm font-medium">Rule ids ({ids.length})</h4>
          <p className="font-mono text-[11px] leading-relaxed text-ink/60">{ids.join(" · ")}</p>
        </div>
      </div>
    </details>
  );
}
