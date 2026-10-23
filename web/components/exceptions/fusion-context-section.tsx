import { ErrorAlert } from "@/components/common/error-alert";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import type { Result } from "@/lib/result";

import { ApplicationsTable } from "./applications-table";
import { AutofixList } from "./autofix-list";
import { CustomerPicker } from "./customer-picker";
import {
  CandidateReceiptsTable,
  ContextWarnings,
  CreditMemoHistory,
  CustomerCard,
  InvoicesTable,
} from "./fusion-context-cards";
import { ReceiptPicker } from "./receipt-picker";

type ContextPromise = Promise<Result<Schemas["FusionContextOut"], ApiError>>;

/** Auto-fix timeline. Streams in under Suspense. */
export async function FusionAutofix({
  context,
  itemState,
}: Readonly<{ context: ContextPromise; itemState: string | null }>): Promise<React.JSX.Element | null> {
  const result = await context;
  if (!result.ok) return null;
  return <AutofixList attempts={result.value.autofix_attempts} itemState={itemState} />;
}

/** The receipt and customer pickers a stuck code calls for. Streams in under Suspense. */
export async function FusionReceiptPicker({
  context,
  errorCode,
}: Readonly<{
  context: ContextPromise;
  errorCode: Schemas["ErrorCode"] | null;
}>): Promise<React.JSX.Element | null> {
  const result = await context;
  if (!result.ok) return null;
  const ctx = result.value;
  return (
    <>
      {errorCode === "RECEIPT_AMBIGUOUS" ? (
        <ReceiptPicker receipts={ctx.candidate_receipts} />
      ) : null}
      {errorCode?.startsWith("CUSTOMER_") ? (
        <CustomerPicker customer={ctx.customer} invoices={ctx.invoices} />
      ) : null}
    </>
  );
}

/** The applied ledger and everything Fusion hides. Streams in under Suspense. */
export async function FusionContextSection({
  context,
  currency,
  canReverse,
}: Readonly<{
  context: ContextPromise;
  currency: string | null;
  canReverse: boolean;
}>): Promise<React.JSX.Element> {
  const result = await context;
  if (!result.ok) {
    return <ErrorAlert error={result.error} title="Couldn't load the Fusion context" />;
  }
  const ctx = result.value;
  return (
    <>
      {ctx.applications.length > 0 ? (
        <ApplicationsTable
          applications={ctx.applications}
          currency={currency}
          canReverse={canReverse}
        />
      ) : null}
      <ContextWarnings warnings={ctx.warnings} />
      <CustomerCard customer={ctx.customer} />
      <CandidateReceiptsTable receipts={ctx.candidate_receipts} />
      <InvoicesTable invoices={ctx.invoices} />
      <CreditMemoHistory memos={ctx.credit_memo_history} />
    </>
  );
}
