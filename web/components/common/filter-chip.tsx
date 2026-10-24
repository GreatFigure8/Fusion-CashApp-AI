"use client";

import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A toggleable filter pill (12.5px). Active chips take the accent border and soft fill. */
export function FilterChip({
  active,
  onClick,
  count,
  disabled = false,
  children,
}: {
  active: boolean;
  onClick: () => void;
  count?: number;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
      data-slot="filter-chip"
      className={cn(
        "inline-flex min-h-8 items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px] transition-colors disabled:pointer-events-none disabled:opacity-50",
        active
          ? "border-brand-hi bg-brand-soft text-brand-ink"
          : "border-line-strong bg-surface-2 text-foreground/80 hover:bg-white/5",
      )}
    >
      {children}
      {count !== undefined ? (
        <span className="font-mono text-label tabular-nums text-muted-foreground">{count}</span>
      ) : null}
    </button>
  );
}

/** A prompt suggestion pill (13px), used by the assistant. */
export function SuggestionChip({
  onClick,
  disabled = false,
  title,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  title?: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      data-slot="suggestion-chip"
      className="inline-flex min-h-[34px] items-center rounded-full border border-line-strong bg-surface-2 px-3.5 py-1.5 text-[13px] text-foreground/80 transition-colors hover:bg-white/5 disabled:pointer-events-none disabled:opacity-50"
    >
      {children}
    </button>
  );
}
