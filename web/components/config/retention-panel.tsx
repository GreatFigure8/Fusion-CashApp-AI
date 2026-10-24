import type { Schemas } from "@/lib/api/types";

import { entriesForGroup } from "./config-registry";
import { PurgeDryRun } from "./purge-dry-run";
import { GroupCard } from "./settings-panel";

/** The retention group card, followed by the purge preview for people who can edit. */
export function RetentionPanel({
  entries,
  group,
  title,
  description,
  canEdit,
  nextVersion,
}: {
  entries: readonly Schemas["ConfigEntry"][];
  group: string;
  title: string;
  description?: string;
  canEdit: boolean;
  nextVersion: number;
}) {
  return (
    <div className="space-y-4">
      <GroupCard
        title={title}
        description={description}
        entries={entriesForGroup(entries, group)}
        nextVersion={nextVersion}
      />
      {canEdit ? <PurgeDryRun /> : null}
    </div>
  );
}
