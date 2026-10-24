import { cn } from "@/lib/utils";

const TONE = {
  ok: "bg-ok shadow-[0_0_10px_var(--ok)]",
  warn: "bg-warn shadow-[0_0_10px_var(--warn)]",
  err: "bg-err shadow-[0_0_10px_var(--err)]",
} as const;

/** A small glowing status dot. The pulse stops under reduced motion. */
export function LiveDot({
  tone = "ok",
  pulse = false,
  className,
}: {
  tone?: "ok" | "warn" | "err";
  pulse?: boolean;
  className?: string;
}) {
  return (
    <span
      aria-hidden
      data-slot="live-dot"
      className={cn(
        "inline-block size-1.5 shrink-0 rounded-full",
        TONE[tone],
        pulse && "animate-live-pulse motion-reduce:animate-none",
        className,
      )}
    />
  );
}
