import { AutofixTable } from "@/components/dashboard/autofix-table";
import { DashboardEmpty } from "@/components/dashboard/dashboard-empty";
import { DashboardLive } from "@/components/dashboard/dashboard-live";
import { MoneyByCurrency } from "@/components/dashboard/money-by-currency";
import { ThroughputChart } from "@/components/dashboard/throughput-chart";
import type { Schemas } from "@/lib/api/types";

export type DashboardData = {
  summary: Schemas["SummaryOut"];
  money: Schemas["MoneyByCurrencyOut"];
  throughput: Schemas["ThroughputOut"];
  autofix: Schemas["AutofixOut"];
  models: Schemas["ModelsOut"];
  activity: Schemas["ActivityOut"];
  cohereUtilisationPct: number | null;
};

/** Server-safe composition of the board. An empty window shows the empty state instead. */
export function DashboardBoard({ data, window }: { data: DashboardData; window: string }) {
  if (data.summary.data.done_items === 0) {
    return <DashboardEmpty window={window} />;
  }
  return (
    <DashboardLive
      key={window}
      initialSummary={data.summary}
      initialActivity={data.activity.data}
      models={data.models.data}
      cohereUtilisationPct={data.cohereUtilisationPct}
      window={window}
    >
      <MoneyByCurrency totals={data.money.data} window={window} />
      <div className="grid gap-4 lg:grid-cols-2">
        <ThroughputChart points={data.throughput.data} window={window} />
        <AutofixTable outcomes={data.autofix.data} window={window} />
      </div>
    </DashboardLive>
  );
}
