import type { ReactNode } from "react";

import { GlassPanel } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { cn } from "@/lib/utils";

export type StateKind = "loading" | "empty" | "error" | "denied";

const DEFAULT_LABEL: Readonly<Record<StateKind, string>> = {
  loading: "Loading",
  empty: "Empty",
  error: "Error",
  denied: "Denied",
};

/** The loading, empty, error and denied card every screen uses. */
export function StateCard({
  kind,
  label,
  headline,
  body,
  actions,
  children,
  className,
}: {
  kind: StateKind;
  label?: string;
  headline: string;
  body?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <GlassPanel
      as="div"
      tone={kind === "error" ? "err" : "default"}
      className={cn("flex min-h-[170px] flex-col justify-center gap-2 p-6", className)}
    >
      <div
        data-slot="state-card"
        data-kind={kind}
        role={kind === "error" ? "alert" : undefined}
        aria-busy={kind === "loading" ? true : undefined}
        className="grid gap-2"
      >
        <MonoLabel className={cn(kind === "error" && "text-err-ink")}>
          {label ?? DEFAULT_LABEL[kind]}
        </MonoLabel>
        <h2 className="text-[17px] font-semibold tracking-[-0.01em]">{headline}</h2>
        {body ? <div className="text-[13px] text-muted-foreground">{body}</div> : null}
        {children}
        {actions ? <div className="mt-2 flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </GlassPanel>
  );
}
