"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";

import { ArtifactViewer } from "@/components/common/artifact-viewer";
import { HistoryTimeline } from "@/components/common/history-timeline";
import {
  LlmChat,
  type ChatActionHandler,
  type ChatActionSpec,
} from "@/components/common/llm-chat";
import { highlightsFor } from "@/components/items/extraction-rows";
import { ExtractionTabs } from "@/components/items/extraction-tabs";
import { HighlightProvider, useHighlight } from "@/components/items/highlight-context";
import { ItemHeader } from "@/components/items/item-header";
import { LinesTable } from "@/components/items/lines-table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Schemas } from "@/lib/api/types";
import { formatWorkItemId } from "@/lib/format";
import { err, ok } from "@/lib/result";

/** Navigation only: a chat action never mutates anything. */
export const ITEM_CHAT_ACTIONS: readonly ChatActionSpec[] = [
  { id: "open_in_workbench", label: "Open in exception workbench" },
];

function Panes({
  detail,
  history,
}: {
  detail: Schemas["ItemDetailOut"];
  history: Schemas["HistoryOut"];
}) {
  const router = useRouter();
  const { active, setActive } = useHighlight();
  const { item, extraction } = detail;
  const highlights = highlightsFor(extraction.final);

  const onAction: ChatActionHandler = async (id) => {
    if (id === "open_in_workbench") {
      router.push(`/exceptions?item=${formatWorkItemId(item.id)}` as Route);
      return ok(undefined);
    }
    return err({
      status: 422,
      code: "unsupported_action",
      message: "That action isn't available here.",
      requestId: null,
      details: [],
    });
  };

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <ItemHeader item={item} lock={detail.lock} />
      <div className="grid min-w-0 gap-3 lg:grid-cols-[2fr_3fr_minmax(320px,1.4fr)]">
        <section aria-label="Artifact" className="min-w-0">
          <ArtifactViewer
            itemId={item.id}
            parts={detail.parts}
            highlights={highlights}
            activeHighlightId={active}
            onHighlightHover={setActive}
          />
        </section>
        <section aria-label="Extraction" className="flex min-w-0 flex-col gap-3">
          <ExtractionTabs extraction={extraction} />
          <LinesTable lines={detail.lines} currency={item.currency} />
        </section>
        <aside aria-label="History and chat" className="min-w-0 rounded-lg border bg-card p-2">
          <Tabs defaultValue="history">
            <TabsList>
              <TabsTrigger value="history">History</TabsTrigger>
              <TabsTrigger value="chat">Chat</TabsTrigger>
            </TabsList>
            <TabsContent value="history" className="p-1">
              <HistoryTimeline entries={history.items} />
            </TabsContent>
            <TabsContent value="chat">
              <LlmChat
                context={{ kind: "item", id: String(item.id) }}
                systemPromptKey="item"
                actions={ITEM_CHAT_ACTIONS}
                onAction={onAction}
                variant="panel"
              />
            </TabsContent>
          </Tabs>
        </aside>
      </div>
    </div>
  );
}

/** Three panes: the artifact with highlights, the extraction and lines, and history plus chat. */
export function ItemView({
  detail,
  history,
}: {
  detail: Schemas["ItemDetailOut"];
  history: Schemas["HistoryOut"];
}) {
  return (
    <HighlightProvider>
      <Panes detail={detail} history={history} />
    </HighlightProvider>
  );
}
