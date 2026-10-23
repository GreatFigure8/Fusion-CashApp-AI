import { cn } from "@/lib/utils";

const FILL = {
  accent: "bg-brand-hi shadow-[0_0_10px_-2px_var(--acc-hi)]",
  ok: "bg-ok",
  warn: "bg-warn",
  err: "bg-err",
} as const;

/** A thin horizontal meter. Out-of-range values are clamped. */
export function Meter({
  value,
  max = 1,
  tone = "accent",
  size = 6,
  label,
  className,
}: {
  value: number;
  max?: number;
  tone?: "accent" | "ok" | "warn" | "err";
  size?: 5 | 6;
  label: string;
  className?: string;
}) {
  const safeMax = max > 0 ? max : 1;
  const clamped = Math.min(safeMax, Math.max(0, Number.isFinite(value) ? value : 0));
  return (
    <div
      role="meter"
      aria-label={label}
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={safeMax}
      data-slot="meter"
      className={cn(
        "overflow-hidden rounded-[3px] bg-white/10",
        size === 5 ? "h-[5px]" : "h-1.5",
        className,
      )}
    >
      <div
        className={cn("h-full rounded-[3px]", FILL[tone])}
        style={{ width: `${(clamped / safeMax) * 100}%` }}
      />
    </div>
  );
}
