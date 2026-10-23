import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill } from "@/components/common/pill";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import type { Result } from "@/lib/result";

import { HistoryList } from "./history-list";

/** The last three changes across every setting; the page's version label counts these rows. */
export function ChangeHistoryCard({
  result,
}: {
  result: Result<Schemas["ConfigChangePage"], ApiError>;
}) {
  return (
    <GlassPanel as="section" aria-label="Change history">
      <PanelHeader title="Change history">
        <Pill tone="muted">last 3</Pill>
      </PanelHeader>
      <PanelBody>
        <HistoryList
          changes={result.ok ? result.value.items : null}
          error={result.ok ? null : result.error}
          topVersion={result.ok ? result.value.total : undefined}
        />
      </PanelBody>
    </GlassPanel>
  );
}
