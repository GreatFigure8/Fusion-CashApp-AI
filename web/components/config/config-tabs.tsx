import Link from "next/link";

import { GlassPanel } from "@/components/common/glass-panel";
import type { Schemas } from "@/lib/api/types";
import { cn } from "@/lib/utils";

export const ALIASES_GROUP_ID = "aliases";

const NOTE =
  "Only the database connection and the secrets master key live outside the database. Every other setting is here, versioned and audited; secrets are stored encrypted.";

/** The group nav: API groups in API order with counts, then the fixed Payer aliases link. */
export function GroupNav({
  groups,
  active,
}: {
  groups: readonly Schemas["ConfigGroupOut"][];
  active: string;
}) {
  const rows = [
    ...groups.map((g) => ({ id: g.group, label: g.label, count: g.count as number | null })),
    { id: ALIASES_GROUP_ID, label: "Payer aliases", count: null },
  ];
  return (
    <GlassPanel
      as="nav"
      aria-label="Setting groups"
      className="p-2 lg:w-60 lg:shrink-0 lg:self-start"
    >
      <ul className="flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
        {rows.map((row) => {
          const current = row.id === active;
          return (
            <li key={row.id}>
              <Link
                href={`/config?group=${encodeURIComponent(row.id)}`}
                aria-current={current ? "page" : undefined}
                className={cn(
                  "flex items-center justify-between gap-3 rounded-lg px-3 py-1.5 text-sm whitespace-nowrap transition-colors hover:bg-muted",
                  current && "bg-brand-soft text-brand-ink ring-1 ring-brand/40",
                )}
              >
                <span>{row.label}</span>
                {row.count === null ? null : (
                  <span className="font-mono text-[11px] text-faint">{row.count}</span>
                )}
              </Link>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 px-3 pb-1 text-xs text-muted-foreground">{NOTE}</p>
    </GlassPanel>
  );
}
