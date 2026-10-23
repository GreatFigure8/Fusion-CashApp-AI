import type * as React from "react";

import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export type AgingRow = Readonly<{ key: string; label: string; count: number }>;

export function AgingTable({ rows }: { rows: readonly AgingRow[] }): React.JSX.Element {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-base font-medium">Aging items</h2>
      <Table>
        <TableCaption className="sr-only">Open items by age</TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead>Age</TableHead>
            <TableHead className="text-right">Items</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.key}>
              <TableCell>{row.label}</TableCell>
              <TableCell className="text-right tabular-nums">{row.count}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </section>
  );
}
