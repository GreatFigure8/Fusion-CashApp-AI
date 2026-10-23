import type * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import type { Schemas } from "@/lib/api/types";
import { formatReportDate } from "@/lib/reports/format";

import { ExportButtons } from "./export-buttons";
import { PartiallyPaidTable } from "./partially-paid-table";
import { ReportDatePicker } from "./report-date-picker";

export function PartiallyPaidView({
  data,
  from,
  to,
  max,
}: {
  data: Schemas["PartiallyPaidResponse"];
  from: string;
  to: string;
  max: string;
}): React.JSX.Element {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <ReportDatePicker mode="range" from={from} to={to} max={max} />
        <ExportButtons target={{ report: "partially-paid", from, to }} />
      </div>
      <PartiallyPaidTable
        rows={data.rows}
        emptyState={
          <EmptyState
            title={`No partially paid invoices between ${formatReportDate(from)} and ${formatReportDate(to)}.`}
          />
        }
      />
      {data.truncated ? (
        <p className="text-sm text-muted-foreground">
          Showing the latest 5,000 rows; export for all.
        </p>
      ) : null}
    </div>
  );
}
