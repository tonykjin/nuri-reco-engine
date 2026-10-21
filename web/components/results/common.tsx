import type { ReactNode } from "react";

export function Recommended() {
  return (
    <span className="rounded-full bg-mist px-2 py-0.5 text-[11px] font-medium tracking-wide text-ink/70 uppercase">
      Recommended
    </span>
  );
}

export function Why({ why, ruleIds }: { why: string; ruleIds?: string[] }) {
  return (
    <details className="group text-sm">
      <summary className="cursor-pointer text-ink/60 select-none hover:text-ink">Why?</summary>
      <p className="mt-1 text-ink/80">{why}</p>
      {ruleIds && ruleIds.length > 0 && (
        <p className="mt-1 font-mono text-[11px] text-ink/40">{ruleIds.join(" · ")}</p>
      )}
    </details>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-2xl bg-white p-5 ${className}`}>{children}</div>;
}

export function Banner({
  tone,
  title,
  children,
}: {
  tone: "hold" | "review" | "notice";
  title: string;
  children?: ReactNode;
}) {
  const styles = {
    hold: "border-ink bg-white",
    review: "border-signal bg-white",
    notice: "border-ink/20 bg-white",
  }[tone];
  return (
    <div role="status" className={`space-y-2 rounded-2xl border-2 p-5 ${styles}`}>
      <p className="font-semibold">{title}</p>
      {children}
    </div>
  );
}

export function Tabs<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { id: T; label: string; hint?: string }[];
  value: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="tab"
          aria-selected={value === o.id}
          onClick={() => onChange(o.id)}
          className={`shrink-0 rounded-full px-3 py-1.5 text-sm ${
            value === o.id ? "bg-ink text-white" : "bg-mist text-ink/70 hover:text-ink"
          }`}
        >
          {o.label}
          {o.hint && <span className="ml-1 text-xs opacity-60">{o.hint}</span>}
        </button>
      ))}
    </div>
  );
}

export const PENDING = "Pending your dietitian";
