import { GlassPanel, PanelHeader } from "@/components/common/glass-panel";
import { Money } from "@/components/common/money";
import { StatusBadge } from "@/components/common/status-badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Schemas } from "@/lib/api/types";

/** Each remittance line with what Fusion held, what was applied and the Fusion result code. */
export function LinesTable({
  lines,
  currency,
}: {
  lines: Schemas["LineOut"][];
  currency: string | null;
}) {
  return (
    <GlassPanel aria-label="Lines" className="min-w-0 overflow-x-auto">
      <PanelHeader title="Lines" titleSize="label" />
      {lines.length === 0 ? (
        <p className="p-3 text-sm text-muted-foreground">No lines have been matched yet.</p>
      ) : (
        <Table className="text-[13px]">
          <TableHeader>
            <TableRow>
              <TableHead className="h-8 text-xs text-muted-foreground">Invoice</TableHead>
              <TableHead className="h-8 text-right text-xs text-muted-foreground">Stated</TableHead>
              <TableHead className="h-8 text-right text-xs text-muted-foreground">
                Fusion balance
              </TableHead>
              <TableHead className="h-8 text-right text-xs text-muted-foreground">Applied</TableHead>
              <TableHead className="h-8 text-xs text-muted-foreground">Status</TableHead>
              <TableHead className="h-8 text-xs text-muted-foreground">Fusion result</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {lines.map((line) => (
              <TableRow key={line.line_no}>
                <TableCell className="font-mono">{line.transaction_number ?? "—"}</TableCell>
                <TableCell className="text-right">
                  <Money amount={line.stated_amount} currency={currency} />
                </TableCell>
                <TableCell className="text-right">
                  <Money amount={line.fusion_balance} currency={currency} />
                </TableCell>
                <TableCell className="text-right">
                  <Money amount={line.applied_amount} currency={currency} />
                </TableCell>
                <TableCell>
                  {line.line_status ? (
                    <StatusBadge kind="line_status" value={line.line_status} />
                  ) : (
                    <span className="text-muted-foreground">Pending</span>
                  )}
                </TableCell>
                <TableCell className="font-mono text-xs">{line.fusion_result_code ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </GlassPanel>
  );
}
