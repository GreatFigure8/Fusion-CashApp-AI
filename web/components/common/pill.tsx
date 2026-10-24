import type { ReactNode } from "react";

import { LiveDot } from "@/components/common/live-dot";
import { cn } from "@/lib/utils";

export type PillTone = "ok" | "accent" | "warn" | "err" | "locked" | "muted";

export const PILL_TONE_CLASSES: Readonly<Record<PillTone, string>> = {
  ok: "bg-ok-soft text-ok-ink",
  accent: "bg-brand-soft text-brand-ink",
  warn: "bg-warn-soft text-warn-ink",
  err: "bg-err-soft text-err-ink",
  locked: "bg-locked-soft text-locked-ink",
  muted: "bg-white/5 text-muted-foreground",
};

function dotTone(tone: PillTone): "ok" | "warn" | "err" {
  if (tone === "warn") return "warn";
  if (tone === "err") return "err";
  return "ok";
}

/** A fully rounded status pill. The tone sets the soft background and the ink colour. */
export function Pill({
  tone,
  dot = false,
  pulse = false,
  mono = false,
  title,
  className,
  children,
}: {
  tone: PillTone;
  dot?: boolean;
  pulse?: boolean;
  mono?: boolean;
  title?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      data-slot="pill"
      data-tone={tone}
      title={title}
      className={cn(
        "inline-flex w-fit shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium",
        PILL_TONE_CLASSES[tone],
        mono && "font-mono",
        className,
      )}
    >
      {dot ? <LiveDot tone={dotTone(tone)} pulse={pulse} /> : null}
      {children}
    </span>
  );
}
