import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/** The mono uppercase micro-label (`.lab` on the boards). */
export function MonoLabel({
  as: Tag = "span",
  className,
  children,
}: {
  as?: "span" | "p" | "div" | "h2" | "h3";
  className?: string;
  children: ReactNode;
}) {
  return (
    <Tag
      data-slot="mono-label"
      className={cn(
        "font-mono text-label uppercase tracking-[0.08em] text-muted-foreground",
        className,
      )}
    >
      {children}
    </Tag>
  );
}
