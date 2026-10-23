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

type Props = Readonly<{
  context: Promise<Result<Schemas["FusionContextOut"], ApiError>>;
  errorCode: Schemas["ErrorCode"] | null;
  currency: string | null;
  canReverse: boolean;
}>;

/** Auto-fix history, the applied ledger and everything Fusion hides. Streams in under Suspense. */
export async function FusionContextSection({
  context,
  errorCode,
  currency,
  canReverse,
}: Props): Promise<React.JSX.Element> {
  const result = await context;
  if (!result.ok) {
    return <ErrorAlert error={result.error} title="Couldn't load the Fusion context" />;
  }
  const ctx = result.value;
  return (
    <>
      <AutofixList attempts={ctx.autofix_attempts} />
      {ctx.applications.length > 0 ? (
        <ApplicationsTable
          applications={ctx.applications}
          currency={currency}
          canReverse={canReverse}
        />
      ) : null}
      <ContextWarnings warnings={ctx.warnings} />
      {errorCode === "RECEIPT_AMBIGUOUS" ? (
        <ReceiptPicker receipts={ctx.candidate_receipts} />
      ) : null}
      {errorCode?.startsWith("CUSTOMER_") ? (
        <CustomerPicker customer={ctx.customer} invoices={ctx.invoices} />
      ) : null}
      <CustomerCard customer={ctx.customer} />
      <CandidateReceiptsTable receipts={ctx.candidate_receipts} />
      <InvoicesTable invoices={ctx.invoices} />
      <CreditMemoHistory memos={ctx.credit_memo_history} />
    </>
  );
}
