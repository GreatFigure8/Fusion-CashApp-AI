import type * as React from "react";

import { EmptyState } from "@/components/common/empty-state";
import { KpiCard } from "@/components/common/kpi-card";
import { Money } from "@/components/common/money";
import type { Schemas } from "@/lib/api/types";
import { formatReportDate, lastGeneratedLabel } from "@/lib/reports/format";

import { AgingTable } from "./aging-table";
import { DailySummaryActions } from "./daily-summary-actions";
import { ExportButtons } from "./export-buttons";
import { FailuresByCodeChart } from "./failures-by-code-chart";
import { ReportDatePicker } from "./report-date-picker";

export function DailySummaryView({
  data,
  date,
  max,
}: {
  data: Schemas["DailySummaryResponse"];
  date: string;
  max: string;
}): React.JSX.Element {
  const s = data.summary;
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-2">
        <ReportDatePicker mode="single" date={date} max={max} />
        <ExportButtons target={{ report: "daily-summary", date }} />
      </div>
      <div className="flex flex-col gap-1">
        <DailySummaryActions date={date} />
        <p className="text-sm text-muted-foreground">
          {lastGeneratedLabel(data.last_generated, data.cutover)}
        </p>
      </div>

      {s.has_activity ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <KpiCard label="Items in" value={s.items_in} />
            <KpiCard
              label="Auto-applied %"
              value={s.auto_applied_pct === null ? "—" : `${s.auto_applied_pct}%`}
              hint={`${s.auto_applied} of ${s.completed} completed`}
            />
            <KpiCard
              label="Amount applied"
              value={
                s.applied_by_currency.length === 0 ? (
                  "—"
                ) : (
                  <span className="flex flex-col">
                    {s.applied_by_currency.map((row) => (
                      <Money key={row.currency} amount={row.amount} currency={row.currency} />
                    ))}
                  </span>
                )
              }
            />
            <KpiCard label="Escalations" value={s.escalations} />
          </div>
          <FailuresByCodeChart rows={s.failures_by_error_code} />
          <AgingTable rows={s.aging_buckets} />
        </>
      ) : (
        <EmptyState title={`No activity on ${formatReportDate(date)}.`} />
      )}
    </div>
  );
}
