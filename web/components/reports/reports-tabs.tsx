"use client";

import { useRouter } from "next/navigation";
import type * as React from "react";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { reportTab, type ReportTab } from "@/lib/reports/schemas";

/** The two report tabs, bound to `?tab=`. The active tab's content is rendered by the server. */
export function ReportsTabs({
  tab,
  children,
}: {
  tab: ReportTab;
  children: React.ReactNode;
}): React.JSX.Element {
  const router = useRouter();
  return (
    <div className="flex flex-col gap-4">
      <Tabs
        value={tab}
        onValueChange={(next) => {
          const parsed = reportTab.safeParse(next);
          if (parsed.success) router.push(`/reports?tab=${parsed.data}`);
        }}
      >
        <TabsList variant="line">
          <TabsTrigger value="daily">Daily summary</TabsTrigger>
          <TabsTrigger value="partial">Partially paid invoices</TabsTrigger>
        </TabsList>
        <TabsContent value={tab}>{children}</TabsContent>
      </Tabs>
    </div>
  );
}
