import { formatMoney } from "@/lib/format";
import { cn } from "@/lib/utils";

/** A money amount: right-aligned, tabular, always with its currency code, never a bare `$`. */
export function Money({
  amount,
  currency,
  className,
}: {
  amount: string | null | undefined;
  currency: string | null | undefined;
  className?: string;
}) {
  return (
    <span className={cn("font-mono tabular-nums text-right", className)}>
      {formatMoney(amount, currency)}
    </span>
  );
}
