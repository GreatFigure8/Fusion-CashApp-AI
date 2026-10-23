import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import type { Result } from "@/lib/result";
import { cn } from "@/lib/utils";

type Props = Readonly<{
  context: Promise<Result<Schemas["FusionContextOut"], ApiError>>;
}>;

function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(`${iso.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
}

/** The receipts that qualify as a match, as small tiles. Streams in under Suspense. */
export async function CandidateReceiptTiles({ context }: Props): Promise<React.JSX.Element | null> {
  const result = await context;
  if (!result.ok) return null;
  const qualifying = result.value.candidate_receipts.filter((r) => r.qualifies || r.chosen);
  if (qualifying.length === 0) return null;
  return (
    <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2" aria-label="Candidate receipts">
      {qualifying.map((receipt) => (
        <li
          key={receipt.receipt_id}
          data-chosen={receipt.chosen ? "true" : undefined}
          className={cn(
            "rounded-xl border px-3 py-2",
            receipt.chosen ? "border-brand-hi bg-brand-soft" : "border-line-strong bg-surface-2",
          )}
        >
          <p className="font-mono text-[13px]">{receipt.receipt_number}</p>
          <p className="text-xs text-muted-foreground">
            {shortDate(receipt.receipt_date)}
            {receipt.customer ? ` · ${receipt.customer}` : ""}
          </p>
        </li>
      ))}
    </ul>
  );
}
