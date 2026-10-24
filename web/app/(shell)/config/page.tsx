import { Suspense } from "react";

import { ErrorAlert } from "@/components/common/error-alert";
import { Pill } from "@/components/common/pill";
import { ForbiddenState } from "@/components/common/require-permission";
import { ChangeHistoryCard } from "@/components/config/change-history-card";
import { ConfigStagingProvider } from "@/components/config/config-staging-provider";
import { ConfigTabSkeleton } from "@/components/config/config-tab-skeleton";
import { GroupNav } from "@/components/config/config-tabs";
import { KeySearch } from "@/components/config/key-search";
import { TopBar } from "@/components/shell/top-bar";
import { hasPermission } from "@/lib/me";

import { GroupBody } from "./_components/group-body";
import { HistoryContent } from "./_components/history-content";
import {
  loadConfigEntries,
  loadConfigGroups,
  loadMe,
  loadRecentChanges,
} from "./_lib/load-config";
import { resolveGroup, searchSchema } from "./_lib/search-params";

export default async function ConfigPage(props: PageProps<"/config">) {
  const params = searchSchema.parse(await props.searchParams);

  // Independent reads start together (DF-4); the API enforces config:read on each.
  const [me, entries, groups, recent] = await Promise.all([
    loadMe(),
    loadConfigEntries(),
    loadConfigGroups(),
    loadRecentChanges(3),
  ]);
  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your profile" />;
  if (!hasPermission(me.value, "config:read")) return <ForbiddenState role="ADMIN" />;
  const canEdit = hasPermission(me.value, "config:write");

  if (!groups.ok) {
    return (
      <>
        <TopBar title="Settings" search={false} />
        <ErrorAlert error={groups.error} title="Couldn't load the setting groups" />
      </>
    );
  }

  const active = resolveGroup(params.group, groups.value);
  const total = recent.ok ? recent.value.total : 0;
  const nextVersion = total + 1;

  return (
    <div className="space-y-4">
      <TopBar
        title="Settings"
        search={false}
        pills={<Pill tone="accent">Stored in the database · v{total}</Pill>}
      >
        <KeySearch initial={params.q} />
      </TopBar>
      <ConfigStagingProvider canEdit={canEdit}>
        <div className="flex flex-col gap-4 lg:flex-row">
          <GroupNav groups={groups.value} active={active} />
          <div className="min-w-0 flex-1 space-y-4">
            <Suspense
              key={`${active}:${params.q}:${params.aq}:${params.apage}`}
              fallback={<ConfigTabSkeleton />}
            >
              <GroupBody
                group={active}
                groups={groups.value}
                entries={entries}
                q={params.q}
                canEdit={canEdit}
                aliasQuery={params.aq}
                aliasPage={params.apage}
                nextVersion={nextVersion}
              />
            </Suspense>
            <ChangeHistoryCard result={recent} />
          </div>
        </div>
      </ConfigStagingProvider>
      {params.history ? (
        <Suspense key={params.history} fallback={null}>
          <HistoryContent settingKey={params.history} />
        </Suspense>
      ) : null}
    </div>
  );
}
