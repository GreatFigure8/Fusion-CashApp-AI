import { AccessPanel } from "@/components/config/access-panel";
import { AliasesPanel } from "@/components/config/aliases-panel";
import type { ConfigTabId } from "@/components/config/config-registry";
import { RetentionPanel } from "@/components/config/retention-panel";
import { SettingsPanel } from "@/components/config/settings-panel";
import { ErrorAlert } from "@/components/common/error-alert";

import {
  loadAliases,
  loadConfigEntries,
  loadGroupRoles,
  loadLatestGroupRolesChange,
} from "../_lib/load-config";

/** Loads what one tab needs and renders it. An API error replaces only this panel. */
export async function TabPanel({
  tab,
  canEdit,
  aliasQuery,
  aliasPage,
}: {
  tab: ConfigTabId;
  canEdit: boolean;
  aliasQuery: string;
  aliasPage: number;
}) {
  if (tab === "aliases") {
    const result = await loadAliases({ q: aliasQuery || undefined, page: aliasPage });
    return (
      <AliasesPanel result={result} q={aliasQuery} pageNumber={aliasPage} canEdit={canEdit} />
    );
  }

  if (tab === "access") {
    const [roles, latest] = await Promise.all([loadGroupRoles(), loadLatestGroupRolesChange()]);
    if (!roles.ok) return <ErrorAlert error={roles.error} title="Couldn't load the group roles" />;
    return (
      <AccessPanel
        groupRoles={roles.value}
        latestChange={latest.ok ? (latest.value.items[0] ?? null) : null}
      />
    );
  }

  const entries = await loadConfigEntries();
  if (!entries.ok) return <ErrorAlert error={entries.error} title="Couldn't load the settings" />;
  if (tab === "retention") return <RetentionPanel entries={entries.value} canEdit={canEdit} />;
  return <SettingsPanel entries={entries.value} tab={tab} />;
}
