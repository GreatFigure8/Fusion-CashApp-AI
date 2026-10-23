import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

const TONE = {
  default: "border-line-strong",
  accent: "border-brand-hi/40 shadow-[0_0_60px_-30px_var(--acc-hi)]",
  warn: "border-warn/40 shadow-[0_0_40px_-22px_var(--warn)]",
  err: "border-err/35",
} as const;

/** The glass surface every bordered block sits on. `solid` drops the blur (chat surfaces). */
export function GlassPanel({
  as: Tag = "section",
  tone = "default",
  solid = false,
  className,
  "aria-label": ariaLabel,
  children,
}: {
  as?: "section" | "div" | "aside" | "nav" | "header" | "footer";
  tone?: "default" | "accent" | "warn" | "err";
  solid?: boolean;
  className?: string;
  "aria-label"?: string;
  children: ReactNode;
}) {
  return (
    <Tag
      data-slot="glass-panel"
      data-tone={tone}
      aria-label={ariaLabel}
      className={cn(
        "rounded-2xl border text-card-foreground shadow-float",
        solid ? "bg-surface-1" : "bg-surface-1/70 backdrop-blur-[14px]",
        TONE[tone],
        className,
      )}
    >
      {children}
    </Tag>
  );
}

const TITLE_SIZE = {
  card: "text-[15px] font-semibold tracking-[-0.01em]",
  page: "text-lg font-semibold tracking-[-0.01em]",
  label: "font-mono text-label uppercase tracking-[0.08em] text-muted-foreground",
} as const;

/** Panel header: title on the left, pills or labels on the right, hairline below. */
export function PanelHeader({
  title,
  titleSize = "card",
  className,
  children,
}: {
  title?: ReactNode;
  titleSize?: "card" | "page" | "label";
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div
      data-slot="panel-header"
      className={cn(
        "flex flex-wrap items-center justify-between gap-2 border-b border-line px-[18px] py-3.5",
        className,
      )}
    >
      {title !== undefined ? <h2 className={TITLE_SIZE[titleSize]}>{title}</h2> : null}
      {children !== undefined ? (
        <div className="flex flex-wrap items-center gap-2">{children}</div>
      ) : null}
    </div>
  );
}

export function PanelBody({
  flush = false,
  className,
  children,
}: {
  flush?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div data-slot="panel-body" className={cn(flush ? "p-0" : "px-[18px] py-4", className)}>
      {children}
    </div>
  );
}
