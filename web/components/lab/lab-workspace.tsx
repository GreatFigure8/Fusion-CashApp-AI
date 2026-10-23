"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useCallback } from "react";

import { LlmChat, type ResultCard } from "@/components/common/llm-chat";
import type { Me } from "@/lib/permissions";
import { hasPermission } from "@/lib/permissions";
import { labViewState, replayCardHref, type LabCandidate, type LabReplay } from "@/lib/lab/view";

import { CandidateCard } from "./candidate-card";
import { ChangedItemsTable } from "./changed-items-table";
import { ComparisonTiles } from "./comparison-tiles";
import {
  LabEmptyState,
  LabNoPermissionNote,
  LabReplayFailed,
  LabStaleState,
  LabUnreplayedState,
} from "./lab-states";
import { MoneyAffectedTable } from "./money-affected-table";
import { PromotePanel } from "./promote-panel";
import { ReplayProgress } from "./replay-progress";

/** The lab split: the shared compact chat on the left, the results it produced on the right. */
export function LabWorkspace({
  me,
  candidate,
  replay,
}: {
  me: Me;
  candidate: LabCandidate | null;
  replay: LabReplay | null;
}) {
  const router = useRouter();
  const state = labViewState(candidate, replay);

  // The results follow the replay the chat started; the server re-reads the data.
  const onToolResult = useCallback(
    (card: ResultCard) => {
      const href = replayCardHref(card);
      if (href) router.replace(href as Route);
    },
    [router],
  );

  const showResults = replay !== null && replay.status === "DONE";
  const writer = hasPermission(me, "config:write");

  return (
    <div className="flex flex-wrap gap-4">
      <div className="min-w-0 flex-[1_1_380px]">
        <LlmChat
          variant="compact"
          systemPromptKey="matching"
          context={{ kind: "matching" }}
          tools={["lab"]}
          title="Lab assistant"
          onToolResult={onToolResult}
        />
      </div>
      <div className="flex min-w-0 flex-[999_1_520px] flex-col gap-4" data-state={state}>
        {candidate === null ? <LabEmptyState /> : <CandidateCard candidate={candidate} replay={replay} />}
        {candidate !== null && state === "unreplayed" ? (
          <LabUnreplayedState candidateId={candidate.id} />
        ) : null}
        {candidate !== null && replay !== null && state === "loading" ? (
          <ReplayProgress key={replay.id} replayId={replay.id} done={replay.done} total={replay.total} />
        ) : null}
        {candidate !== null && state === "failed" ? <LabReplayFailed candidateId={candidate.id} /> : null}
        {candidate !== null && state === "stale" ? (
          <LabStaleState candidateId={candidate.id} liveVersion={candidate.live_version} />
        ) : null}
        {showResults ? (
          <>
            <ComparisonTiles replay={replay} />
            <MoneyAffectedTable rows={replay.money_by_currency} />
            <ChangedItemsTable replayId={replay.id} items={replay.items} />
          </>
        ) : null}
        {candidate !== null && replay !== null && state === "done" ? (
          <>
            <PromotePanel me={me} candidate={candidate} replay={replay} />
            {writer ? null : <LabNoPermissionNote />}
          </>
        ) : null}
      </div>
    </div>
  );
}
