import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { Money } from "@/components/common/money";
import type { Schemas } from "@/lib/api/types";

type CurrencyTotal = Schemas["CurrencyTotal"];

/** One tile per currency. There is deliberately no total: currencies are never summed. */
export function MoneyByCurrency({
  totals,
  window,
}: {
  totals: readonly CurrencyTotal[];
  window: string;
}) {
  return (
    <GlassPanel as="section" aria-label="Money applied by currency">
      <PanelHeader title="Money applied by currency">
        <MonoLabel>{window} · never summed across currencies</MonoLabel>
      </PanelHeader>
      <PanelBody>
        {totals.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing applied in this window.</p>
        ) : (
          <ul className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
            {totals.map((total) => (
              <li
                key={total.currency}
                data-slot="currency-tile"
                className="flex flex-col gap-1 rounded-lg border border-white/10 bg-white/[0.03] p-3"
              >
                <MonoLabel>{total.currency}</MonoLabel>
                <Money
                  amount={total.amount}
                  currency={total.currency}
                  className="text-[20px] text-left"
                />
                <span className="font-mono text-xs text-muted-foreground">
                  {total.receipts} receipts · residual {total.residual}
                </span>
              </li>
            ))}
          </ul>
        )}
      </PanelBody>
    </GlassPanel>
  );
}
