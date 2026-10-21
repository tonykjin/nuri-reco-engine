"use client";

// Building blocks for one-question screens: big tap targets, short copy.

import type { ReactNode } from "react";

export function Helper({ children }: { children: ReactNode }) {
  return <p className="text-sm text-ink/70">{children}</p>;
}

export function Label({ children }: { children: ReactNode }) {
  return <p className="text-sm font-medium">{children}</p>;
}

export function Choice({
  selected,
  onClick,
  label,
  hint,
}: {
  selected: boolean;
  onClick: () => void;
  label: string;
  hint?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={`flex min-h-14 w-full flex-col justify-center rounded-xl border-2 px-4 py-3 text-left transition ${
        selected ? "border-signal bg-white" : "border-transparent bg-white hover:border-ink/20"
      }`}
    >
      <span className="font-medium">{label}</span>
      {hint && <span className="text-sm text-ink/60">{hint}</span>}
    </button>
  );
}

export function ChoiceList<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { id: T; label: string; hint?: string }[];
  value: T | null;
  onChange: (id: T) => void;
}) {
  return (
    <div className="space-y-2" role="radiogroup">
      {options.map((o) => (
        <Choice
          key={o.id}
          label={o.label}
          hint={o.hint}
          selected={value === o.id}
          onClick={() => onChange(o.id)}
        />
      ))}
    </div>
  );
}

export function Chip({
  selected,
  onClick,
  children,
  disabled,
}: {
  selected: boolean;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      disabled={disabled}
      onClick={onClick}
      className={`min-h-11 rounded-full border-2 px-4 py-2 text-sm transition disabled:opacity-40 ${
        selected
          ? "border-ink bg-ink text-white"
          : "border-transparent bg-white hover:border-ink/20"
      }`}
    >
      {children}
    </button>
  );
}

export function Chips<T extends string>({
  options,
  values,
  onToggle,
  max,
}: {
  options: { id: T; label: string }[];
  values: T[];
  onToggle: (id: T) => void;
  max?: number;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((o) => {
        const selected = values.includes(o.id);
        return (
          <Chip
            key={o.id}
            selected={selected}
            disabled={!selected && max !== undefined && values.length >= max}
            onClick={() => onToggle(o.id)}
          >
            {o.label}
          </Chip>
        );
      })}
    </div>
  );
}

export function toggle<T>(values: T[], value: T): T[] {
  return values.includes(value) ? values.filter((v) => v !== value) : [...values, value];
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: { id: T; label: string }[];
  value: T | null;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div className="flex rounded-full bg-white p-1" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={value === o.id}
          onClick={() => onChange(o.id)}
          className={`min-h-10 flex-1 rounded-full px-3 text-sm transition ${
            value === o.id ? "bg-ink text-white" : "text-ink/70"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A number input whose empty state is null. */
export function NumberField({
  label,
  value,
  onChange,
  unit,
  min = 0,
  step = "any",
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  unit?: string;
  min?: number;
  step?: number | "any";
}) {
  return (
    <label className="block flex-1 space-y-1">
      <span className="text-sm text-ink/70">{label}</span>
      <span className="flex items-center rounded-xl bg-white px-4">
        <input
          type="number"
          inputMode="decimal"
          min={min}
          step={step}
          className="min-h-14 w-full bg-transparent text-lg outline-none"
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
        {unit && <span className="text-sm text-ink/60">{unit}</span>}
      </span>
    </label>
  );
}

export function DateField({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  value: string | null | undefined;
  onChange: (value: string | null) => void;
  min?: string;
  max?: string;
}) {
  return (
    <label className="block space-y-1">
      <span className="text-sm text-ink/70">{label}</span>
      <input
        type="date"
        min={min}
        max={max}
        className="min-h-14 w-full rounded-xl bg-white px-4 text-lg"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      />
    </label>
  );
}

export function YesNo({
  value,
  onChange,
  label,
  disabled,
}: {
  value: boolean | null;
  onChange: (value: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <div className={`space-y-2 rounded-xl bg-white p-4 ${disabled ? "opacity-40" : ""}`}>
      <p className="text-sm">{label}</p>
      <div className="flex gap-2">
        {[
          { v: false, text: "No" },
          { v: true, text: "Yes" },
        ].map(({ v, text }) => (
          <button
            key={text}
            type="button"
            disabled={disabled}
            aria-pressed={value === v}
            onClick={() => onChange(v)}
            className={`min-h-11 flex-1 rounded-lg border-2 text-sm ${
              value === v ? "border-ink bg-ink text-white" : "border-ink/10"
            }`}
          >
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}
