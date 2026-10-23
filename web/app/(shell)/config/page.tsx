import { Suspense } from "react";
import { z } from "zod";

import { ErrorAlert } from "@/components/common/error-alert";
import { ForbiddenState } from "@/components/common/require-permission";
import { CONFIG_TABS, type ConfigTabId } from "@/components/config/config-registry";
import { ConfigStagingProvider } from "@/components/config/config-staging-provider";
import { ConfigTabSkeleton } from "@/components/config/config-tab-skeleton";
import { ConfigTabs } from "@/components/config/config-tabs";
import { SaveFooter } from "@/components/config/save-footer";
import { TopBar } from "@/components/shell/top-bar";
import { hasPermission } from "@/lib/me";

import { HistoryContent } from "./_components/history-content";
import { TabPanel } from "./_components/tab-panel";
import { loadMe } from "./_lib/load-config";

const tabIds = CONFIG_TABS.map((t) => t.id) as [ConfigTabId, ...ConfigTabId[]];

/** First value of a search param; an unknown or malformed value falls back to the default. */
const first = (v: unknown): unknown => (Array.isArray(v) ? v[0] : v);

const searchSchema = z.object({
  tab: z.preprocess(first, z.enum(tabIds).catch("access")),
  history: z.preprocess(first, z.string().regex(/^[a-z0-9_.]{1,100}$/).optional().catch(undefined)),
  aq: z.preprocess(first, z.string().trim().max(200).catch("")).default(""),
  apage: z.preprocess(first, z.coerce.number().int().min(1).catch(1)).default(1),
});

export default async function ConfigPage(props: PageProps<"/config">) {
  const params = searchSchema.parse(await props.searchParams);

  const me = await loadMe();
  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your profile" />;
  if (!hasPermission(me.value, "config:read")) return <ForbiddenState role="ADMIN" />;
  const canEdit = hasPermission(me.value, "config:write");

  return (
    <div className="space-y-4">
      <TopBar title="Settings" />
      <ConfigStagingProvider canEdit={canEdit}>
        <div className="flex flex-col gap-4 lg:flex-row">
          <ConfigTabs active={params.tab} />
          <div className="min-w-0 flex-1">
            <Suspense key={params.tab} fallback={<ConfigTabSkeleton tab={params.tab} />}>
              <TabPanel
                tab={params.tab}
                canEdit={canEdit}
                aliasQuery={params.aq}
                aliasPage={params.apage}
              />
            </Suspense>
            <SaveFooter />
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
