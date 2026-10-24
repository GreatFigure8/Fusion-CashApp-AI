import Link from "next/link";

import { ErrorAlert } from "@/components/common/error-alert";
import { StateCard } from "@/components/common/state-card";
import { AccessPanel } from "@/components/config/access-panel";
import { AliasesPanel } from "@/components/config/aliases-panel";
import { entriesForGroup } from "@/components/config/config-registry";
import { didYouMean, searchEntries } from "@/components/config/key-match";
import { McpConnectionCard } from "@/components/config/mcp-connection-card";
import { RetentionPanel } from "@/components/config/retention-panel";
import { GroupCard } from "@/components/config/settings-panel";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import type { Result } from "@/lib/result";

import {
  loadAliases,
  loadGroupRoles,
  loadLatestGroupRolesChange,
  loadMcpStatus,
} from "../_lib/load-config";
import { ALIASES_GROUP } from "../_lib/search-params";

const MCP_URL_KEY = "mcp.server_url";

/** Loads what the active group needs and renders it. An API error replaces only this body. */
export async function GroupBody({
  group,
  groups,
  entries,
  q,
  canEdit,
  aliasQuery,
  aliasPage,
  nextVersion,
}: {
  group: string;
  groups: readonly Schemas["ConfigGroupOut"][];
  entries: Result<Schemas["ConfigEntry"][], ApiError>;
  q: string;
  canEdit: boolean;
  aliasQuery: string;
  aliasPage: number;
  nextVersion: number;
}) {
  if (!entries.ok && group !== ALIASES_GROUP) {
    return <ErrorAlert error={entries.error} title="Couldn't load the settings" />;
  }
  const all = entries.ok ? entries.value : [];

  if (q !== "") {
    const hits = searchEntries(all, q);
    if (hits.length > 0) {
      return <GroupCard title={`Results for “${q}”`} entries={hits} nextVersion={nextVersion} />;
    }
    const suggestion = didYouMean(
      q,
      all.map((e) => e.key),
    );
    return (
      <StateCard
        kind="empty"
        label="Empty · search"
        headline={`No setting matches “${q}”`}
        body={
          suggestion ? (
            <>
              Did you mean{" "}
              <Link
                href={`/config?group=${encodeURIComponent(group)}&q=${encodeURIComponent(suggestion)}`}
                className="font-mono text-brand-ink underline underline-offset-2"
              >
                {suggestion}
              </Link>
              ?
            </>
          ) : (
            "Try part of a key, such as tolerance or poll."
          )
        }
      />
    );
  }

  if (group === ALIASES_GROUP) {
    const result = await loadAliases({ q: aliasQuery || undefined, page: aliasQuery ? 1 : aliasPage });
    return (
      <AliasesPanel result={result} q={aliasQuery} pageNumber={aliasPage} canEdit={canEdit} />
    );
  }

  const meta = groups.find((g) => g.group === group);
  const title = meta?.label ?? group;

  if (group === "access") {
    const [roles, latest] = await Promise.all([loadGroupRoles(), loadLatestGroupRolesChange()]);
    if (!roles.ok) return <ErrorAlert error={roles.error} title="Couldn't load the group roles" />;
    return (
      <AccessPanel
        groupRoles={roles.value}
        latestChange={latest.ok ? (latest.value.items[0] ?? null) : null}
        nextVersion={nextVersion}
      />
    );
  }

  if (group === "retention") {
    return (
      <RetentionPanel
        entries={all}
        group={group}
        title={title}
        description={meta?.description}
        canEdit={canEdit}
        nextVersion={nextVersion}
      />
    );
  }

  const rows = entriesForGroup(all, group);

  // The connection card keys off the group that holds mcp.server_url, not a group id string.
  const serverUrl = rows.find((e) => e.key === MCP_URL_KEY);
  if (serverUrl) {
    const status = await loadMcpStatus();
    return (
      <GroupCard
        title={title}
        description={meta?.description}
        entries={rows.filter((e) => e.key !== MCP_URL_KEY)}
        nextVersion={nextVersion}
        extra={
          <McpConnectionCard
            status={status}
            entry={serverUrl}
            canEdit={canEdit}
            canTest={canEdit}
          />
        }
      />
    );
  }

  return (
    <GroupCard
      title={title}
      description={meta?.description}
      entries={rows}
      nextVersion={nextVersion}
    />
  );
}
