import { TriangleAlert } from "lucide-react";

import { Money } from "@/components/common/money";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { MonoLabel } from "@/components/common/mono-label";
import { Pill } from "@/components/common/pill";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { Schemas } from "@/lib/api/types";

function Section({
  title,
  children,
}: Readonly<{ title: string; children: React.ReactNode }>): React.JSX.Element {
  return (
    <section className="grid gap-2">
      <MonoLabel as="h3">{title}</MonoLabel>
      {children}
    </section>
  );
}

function Scroll({ children }: Readonly<{ children: React.ReactNode }>): React.JSX.Element {
  return <div className="overflow-x-auto rounded-xl border border-line-strong bg-surface-2">{children}</div>;
}

const NONE = <p className="text-sm text-muted-foreground">None found in Fusion.</p>;

export function CustomerCard({
  customer,
}: Readonly<{ customer: Schemas["CustomerContextOut"] | null }>): React.JSX.Element {
  if (!customer) {
    return (
      <Section title="Customer">
        <p className="text-sm text-muted-foreground">No customer has been resolved yet.</p>
      </Section>
    );
  }
  const site = customer.bill_to_site;
  return (
    <Section title="Customer">
      <div className="grid gap-1 rounded-xl border border-line-strong bg-surface-2 p-3 text-sm">
        <p>
          <span className="font-mono">{customer.account_number}</span> · {customer.name}
        </p>
        <p className="text-muted-foreground">
          Bill-to site {site ? <span className="font-mono">{site.site_number}</span> : "unknown"}
          {customer.location ? ` · ${customer.location}` : ""}
          {site?.address ? ` · ${site.address}` : ""}
        </p>
        {customer.relationships.length > 0 ? (
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Pays on behalf:</span>
            {customer.relationships.map((rel) => (
              <Pill key={rel.account_number} tone="muted" mono>
                {rel.account_number}
                {rel.name ? ` · ${rel.name}` : ""} ({rel.directions.join(" / ").toLowerCase()})
              </Pill>
            ))}
          </div>
        ) : null}
      </div>
    </Section>
  );
}

export function CandidateReceiptsTable({
  receipts,
}: Readonly<{ receipts: readonly Schemas["CandidateReceiptOut"][] }>): React.JSX.Element {
  return (
    <Section title="Candidate receipts">
      {receipts.length === 0 ? (
        NONE
      ) : (
        <Scroll>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Receipt</TableHead>
                <TableHead>Date</TableHead>
                <TableHead className="text-right">Amount</TableHead>
                <TableHead className="text-right">Remaining</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Match</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {receipts.map((r) => (
                <TableRow key={r.receipt_id}>
                  <TableCell className="font-mono">{r.receipt_number}</TableCell>
                  <TableCell>{r.receipt_date ?? "—"}</TableCell>
                  <TableCell className="text-right">
                    <Money amount={r.amount} currency={r.currency} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Money amount={r.remaining} currency={r.currency} />
                    {r.stale ? <span className="ml-1 text-xs text-muted-foreground">(stored)</span> : null}
                  </TableCell>
                  <TableCell className="font-mono">{r.customer ?? "—"}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {r.chosen ? "chosen · " : ""}
                    {r.qualifies ? "qualifies" : "does not qualify"} · {r.score.toFixed(2)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Scroll>
      )}
    </Section>
  );
}

export function InvoicesTable({
  invoices,
}: Readonly<{ invoices: readonly Schemas["InvoiceContextOut"][] }>): React.JSX.Element {
  return (
    <Section title="Invoices">
      {invoices.length === 0 ? (
        NONE
      ) : (
        <Scroll>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Invoice</TableHead>
                <TableHead>Bill-to customer</TableHead>
                <TableHead className="text-right">Original</TableHead>
                <TableHead className="text-right">Remaining</TableHead>
                <TableHead>Currency</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invoices.map((inv) => (
                <TableRow key={inv.customer_trx_id}>
                  <TableCell className="font-mono">{inv.number}</TableCell>
                  <TableCell className="font-mono">{inv.bill_to_customer ?? "—"}</TableCell>
                  <TableCell className="text-right">
                    <Money amount={inv.original_amount} currency={inv.currency} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Money amount={inv.remaining} currency={inv.currency} />
                  </TableCell>
                  <TableCell className="font-mono">{inv.currency}</TableCell>
                  <TableCell>{inv.status}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Scroll>
      )}
    </Section>
  );
}

export function CreditMemoHistory({
  memos,
}: Readonly<{ memos: readonly Schemas["CreditMemoHistoryOut"][] }>): React.JSX.Element | null {
  if (memos.length === 0) return null;
  return (
    <Section title="Credit memo history">
      <div className="grid gap-3">
        {memos.map((memo) => (
          <div key={memo.customer_trx_id} className="rounded-xl border border-line-strong bg-surface-2 p-3 text-sm">
            <p className="flex flex-wrap items-center gap-x-3">
              <span className="font-mono">{memo.number}</span>
              <span className="text-muted-foreground">original</span>
              <Money amount={memo.original} currency={memo.currency} />
              <span className="text-muted-foreground">remaining</span>
              <Money amount={memo.remaining} currency={memo.currency} />
            </p>
            {memo.applications.length === 0 ? (
              <p className="text-muted-foreground">No applications yet.</p>
            ) : (
              <ul className="mt-1 grid gap-0.5 text-muted-foreground">
                {memo.applications.map((a) => (
                  <li key={a.application_id}>
                    {a.apply_date} · receipt <span className="font-mono">{a.receipt_id}</span> ·{" "}
                    <Money amount={a.amount_applied} currency={memo.currency} /> · {a.status}
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </Section>
  );
}

export function ContextWarnings({
  warnings,
}: Readonly<{ warnings: readonly Schemas["ContextWarningOut"][] }>): React.JSX.Element | null {
  if (warnings.length === 0) return null;
  return (
    <Alert>
      <TriangleAlert />
      <AlertTitle>Some Fusion data could not be loaded</AlertTitle>
      <AlertDescription>
        <ul className="grid gap-0.5">
          {warnings.map((w, i) => (
            <li key={`${w.section}-${i}`}>
              {w.section.replace("_", " ")}: {w.message}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
