import type { ReactNode } from "react";

import { GlassPanel } from "@/components/common/glass-panel";
import { Meter } from "@/components/common/meter";
import { MonoLabel } from "@/components/common/mono-label";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

type KpiTone = "default" | "accent" | "warn" | "ok" | "err";

const TONE_TEXT: Readonly<Record<KpiTone, string>> = {
  default: "",
  accent: "text-brand-ink",
  warn: "text-warn-ink",
  ok: "text-ok-ink",
  err: "text-err-ink",
};

const METER_TONE = { default: "accent", accent: "accent", warn: "warn", ok: "ok", err: "err" } as const;
const RING_STROKE: Readonly<Record<KpiTone, string>> = {
  default: "var(--acc-hi)",
  accent: "var(--acc-hi)",
  warn: "var(--warn)",
  ok: "var(--ok)",
  err: "var(--err)",
};

function Ring({ progress, tone, label }: { progress: number; tone: KpiTone; label: string }) {
  const clamped = Math.min(1, Math.max(0, Number.isFinite(progress) ? progress : 0));
  const radius = 30;
  const circumference = 2 * Math.PI * radius;
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox="0 0 72 72"
      className="size-[72px] shrink-0 -rotate-90"
      data-slot="kpi-ring"
    >
      <circle cx="36" cy="36" r={radius} fill="none" stroke="#ffffff14" strokeWidth="6" />
      <circle
        cx="36"
        cy="36"
        r={radius}
        fill="none"
        stroke={RING_STROKE[tone]}
        strokeWidth="6"
        strokeLinecap="round"
        strokeDasharray={`${circumference * clamped} ${circumference}`}
      />
    </svg>
  );
}

export function KpiCard({
  label,
  value,
  hint,
  loading = false,
  variant = "plain",
  progress,
  tone = "default",
  size = "default",
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  loading?: boolean;
  variant?: "plain" | "ring" | "meter";
  progress?: number;
  tone?: KpiTone;
  size?: "default" | "sm";
  className?: string;
}) {
  const valueClass = cn(
    "font-mono font-medium tabular-nums tracking-[-0.02em]",
    size === "sm" ? "text-xl" : "text-[30px] leading-9",
    TONE_TEXT[tone],
  );
  return (
    <GlassPanel
      as="div"
      className={cn("flex flex-col gap-1.5 p-4", className)}
    >
      <div data-slot="kpi-card" className="flex items-center gap-4">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <MonoLabel>{label}</MonoLabel>
          {loading ? <Skeleton className="h-7 w-24" /> : <div className={valueClass}>{value}</div>}
          {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
        </div>
        {variant === "ring" && !loading && progress !== undefined ? (
          <Ring progress={progress} tone={tone} label={`${label} progress`} />
        ) : null}
      </div>
      {variant === "meter" && !loading && progress !== undefined ? (
        <Meter value={progress} tone={METER_TONE[tone]} label={`${label} progress`} />
      ) : null}
    </GlassPanel>
  );
}
