import type { Metadata } from "next";

import { ErrorAlert } from "@/components/common/error-alert";
import { Pill } from "@/components/common/pill";
import { RequirePermission } from "@/components/common/require-permission";
import { LabWorkspace } from "@/components/lab/lab-workspace";
import { TopBar } from "@/components/shell/top-bar";
import { api } from "@/lib/api/client";
import { parseLabSearch } from "@/lib/lab/schemas";
import { getMe } from "@/lib/me";
import { ROUTE_PERMISSIONS } from "@/lib/permissions";

export const metadata: Metadata = { title: "Matching Lab" };

const CANDIDATE_PAGE = 20;

export default async function LabPage(props: PageProps<"/lab">) {
  const search = parseLabSearch(await props.searchParams);

  // Started together (DF-4); an explicit replay id does not wait for the candidate list.
  const [me, candidates, picked] = await Promise.all([
    getMe(),
    api("get", "/lab/candidates", { query: { limit: CANDIDATE_PAGE } }),
    search.replay
      ? api("get", "/lab/replays/{replay_id}", { params: { replay_id: search.replay } })
      : Promise.resolve(null),
  ]);
  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your account" />;
  const gate = ROUTE_PERMISSIONS["/lab"];
  const header = (
    <TopBar
      title="Matching Lab"
      pills={
        <>
          <Pill tone="locked">Read-only replay</Pill>
          <span className="text-xs text-muted-foreground">Replays never write to Fusion</span>
        </>
      }
    />
  );
  if (!candidates.ok) {
    return (
      <RequirePermission me={me.value} permission={gate.permission} role={gate.role}>
        <div className="flex flex-col gap-4">
          {header}
          <ErrorAlert error={candidates.error} title="Couldn't load the lab" />
        </div>
      </RequirePermission>
    );
  }

  const items = candidates.value.items;
  const replayFromUrl = picked?.ok ? picked.value : null;
  const candidate =
    items.find((c) => c.id === (search.candidate ?? replayFromUrl?.candidate_id)) ??
    items[0] ??
    null;

  // The replay the URL names, if it belongs to the candidate; otherwise the candidate's latest.
  let replay = replayFromUrl !== null && replayFromUrl.candidate_id === candidate?.id ? replayFromUrl : null;
  if (replay === null && candidate?.latest_replay) {
    const latest = await api("get", "/lab/replays/{replay_id}", {
      params: { replay_id: candidate.latest_replay.id },
    });
    if (!latest.ok) {
      return (
        <RequirePermission me={me.value} permission={gate.permission} role={gate.role}>
          <div className="flex flex-col gap-4">
            {header}
            <ErrorAlert error={latest.error} title="Couldn't load the replay" />
          </div>
        </RequirePermission>
      );
    }
    replay = latest.value;
  }

  return (
    <RequirePermission me={me.value} permission={gate.permission} role={gate.role}>
      <div className="flex flex-col gap-4">
        {header}
        <LabWorkspace me={me.value} candidate={candidate} replay={replay} />
      </div>
    </RequirePermission>
  );
}
