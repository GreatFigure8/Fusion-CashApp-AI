import type * as React from "react";

import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { StateCard } from "@/components/common/state-card";
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
      <GlassPanel>
        <PanelHeader title="Partially paid invoices" />
        <PanelBody flush>
          <PartiallyPaidTable
            rows={data.rows}
            emptyState={
              <StateCard
                kind="empty"
                headline={`No partially paid invoices between ${formatReportDate(from)} and ${formatReportDate(to)}.`}
              />
            }
          />
        </PanelBody>
      </GlassPanel>
      {data.truncated ? (
        <p className="font-mono text-xs text-muted-foreground">
          Showing the latest 5,000 rows; export for all.
        </p>
      ) : null}
    </div>
  );
}
