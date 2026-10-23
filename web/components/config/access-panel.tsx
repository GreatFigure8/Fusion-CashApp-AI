import type { Schemas } from "@/lib/api/types";

import { GROUP_ROLE_KEY } from "./config-registry";
import { SettingRow } from "./setting-row";

/** The group-to-role map as a pseudo setting, so it shares rows, staging, footer and review with the rest. */
export function AccessPanel({
  groupRoles,
  latestChange,
}: {
  groupRoles: Schemas["GroupRolesResponse"];
  latestChange: Schemas["ConfigChangeOut"] | null;
}) {
  return (
    <SettingRow
      entry={{
        key: GROUP_ROLE_KEY,
        // The API's PUT has no version check (last writer wins). The newest change id stands in for
        // a version: 0 means "default", and it moves with every save so the row re-reads its value.
        version: latestChange?.id ?? 0,
        value: groupRoles.mappings,
        description:
          "Maps identity-domain groups to app roles. At least one group must map to ADMIN.",
        updated_by_name: latestChange?.changed_by_name ?? null,
        updated_at: latestChange?.changed_at ?? groupRoles.updated_at,
      }}
    />
  );
}
