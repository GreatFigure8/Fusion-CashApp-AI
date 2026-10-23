import type { ComponentProps } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type ActionVariant =
  | "default"
  | "outline"
  | "secondary"
  | "ghost"
  | "destructive"
  | "link"
  | "warn"
  | "warn-solid";

type ButtonSize = NonNullable<Parameters<typeof buttonVariants>[0]>["size"];
type BaseVariant = Exclude<ActionVariant, "warn" | "warn-solid">;

const EXTRA: Readonly<Record<"warn" | "warn-solid", string>> = {
  warn: "border-warn/40 bg-warn-soft text-warn-ink hover:bg-warn/20 dark:bg-warn-soft dark:hover:bg-warn/20",
  "warn-solid":
    "border-transparent bg-warn text-[#1b1300] hover:bg-warn/90 dark:bg-warn dark:hover:bg-warn/90",
};

const GLOW = "shadow-[0_0_24px_-8px_var(--acc-hi)]";

/** The `ui/button` variant to render and the extra classes the warn tones and glow add. */
function resolve(variant: ActionVariant, glow: boolean): { base: BaseVariant; extra: string } {
  const isExtra = variant === "warn" || variant === "warn-solid";
  return {
    base: isExtra ? "outline" : variant,
    extra: cn(isExtra && EXTRA[variant], glow && GLOW),
  };
}

/** Button classes with the extra `warn` and `warn-solid` tones; `ui/button` itself is untouched. */
export function actionButtonVariants(
  o: { variant?: ActionVariant; size?: ButtonSize; glow?: boolean; className?: string } = {},
): string {
  const { base, extra } = resolve(o.variant ?? "default", o.glow ?? false);
  return cn(buttonVariants({ variant: base, size: o.size }), extra, o.className);
}

export function ActionButton({
  variant = "default",
  glow = false,
  className,
  ...props
}: Omit<ComponentProps<typeof Button>, "variant"> & { variant?: ActionVariant; glow?: boolean }) {
  const { base, extra } = resolve(variant, glow);
  return <Button {...props} variant={base} className={cn(extra, className)} />;
}
