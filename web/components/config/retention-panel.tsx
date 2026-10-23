import type { Schemas } from "@/lib/api/types";

import { PurgeDryRun } from "./purge-dry-run";
import { SettingsPanel } from "./settings-panel";

export function RetentionPanel({
  entries,
  canEdit,
}: {
  entries: readonly Schemas["ConfigEntry"][];
  canEdit: boolean;
}) {
  return (
    <div className="space-y-4">
      <SettingsPanel entries={entries} tab="retention" />
      {canEdit ? <PurgeDryRun /> : null}
    </div>
  );
}
