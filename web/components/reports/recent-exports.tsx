import type * as React from "react";

import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { whoWhen } from "@/lib/reports/html";
import type { ReportExportOut } from "@/lib/reports/schemas";

/** The log of exported HTML reports: mono file name, then who and when. */
export function RecentExports({
  exports,
  now,
}: {
  exports: readonly ReportExportOut[];
  now: Date;
}): React.JSX.Element {
  return (
    <GlassPanel>
      <PanelHeader title="Recent exports" />
      <PanelBody>
        {exports.length === 0 ? (
          <p className="text-sm text-muted-foreground">No exports yet</p>
        ) : (
          <ul className="flex flex-col">
            {exports.map((row) => (
              <li
                key={row.id}
                className="flex justify-between gap-2 border-b border-white/5 py-2 text-[13px] last:border-b-0"
              >
                <span className="font-mono text-[12.5px]">{row.filename}</span>
                <span className="text-muted-foreground">
                  {whoWhen(row.actor_name, row.at, now)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </PanelBody>
    </GlassPanel>
  );
}
