"use client";

import { MonoLabel } from "@/components/common/mono-label";
import { Money } from "@/components/common/money";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Schemas } from "@/lib/api/types";

import { ReverseDialog } from "./reverse-dialog";
import { useSheet } from "./sheet-context";

type Props = Readonly<{
  applications: readonly Schemas["LedgerApplicationOut"][];
  currency: string | null;
  /** The viewer holds `apply:reverse`. */
  canReverse: boolean;
}>;

/** The applied ledger: what the system put on the receipt, line by line. */
export function ApplicationsTable({ applications, currency, canReverse }: Props): React.JSX.Element {
  const sheet = useSheet();
  const holdsLock = sheet.sheet.lock.kind === "mine";
  const showActions = canReverse;

  return (
    <section className="grid gap-2" aria-labelledby="applications-title">
      <MonoLabel as="h3">
        <span id="applications-title">Applied to Fusion</span>
      </MonoLabel>
      <div className="overflow-x-auto rounded-xl border border-line-strong bg-surface-2">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Line</TableHead>
              <TableHead>Transaction</TableHead>
              <TableHead>Receipt</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead>Status</TableHead>
              {showActions ? <TableHead /> : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {applications.map((row) => {
              const reversible =
                row.status === "APPLIED" &&
                row.fusion_application_id !== null &&
                row.receipt_number !== null;
              return (
                <TableRow key={row.ledger_id}>
                  <TableCell className="font-mono">{row.line_no}</TableCell>
                  <TableCell className="font-mono">{row.transaction_number ?? "—"}</TableCell>
                  <TableCell className="font-mono">{row.receipt_number ?? row.receipt_id}</TableCell>
                  <TableCell className="text-right">
                    <Money amount={row.amount} currency={currency} />
                  </TableCell>
                  <TableCell>
                    {row.reversed_at ? `Reversed by ${row.reversed_by ?? "unknown"}` : row.status}
                  </TableCell>
                  {showActions ? (
                    <TableCell className="text-right">
                      {reversible && holdsLock && row.receipt_number ? (
                        <ReverseDialog
                          ledgerId={row.ledger_id}
                          receiptNumber={row.receipt_number}
                        />
                      ) : null}
                    </TableCell>
                  ) : null}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
      {canReverse && !holdsLock ? (
        <p className="text-xs text-muted-foreground">
          Dequeue the item to reverse an application.
        </p>
      ) : null}
    </section>
  );
}
