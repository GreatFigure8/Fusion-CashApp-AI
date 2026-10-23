"use client";

import { ArtifactViewer } from "@/components/common/artifact-viewer";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { HistoryTimeline } from "@/components/common/history-timeline";
import { LlmChat } from "@/components/common/llm-chat";
import { highlightsFor } from "@/components/items/extraction-rows";
import { ExtractionTabs } from "@/components/items/extraction-tabs";
import { HighlightProvider, useHighlight } from "@/components/items/highlight-context";
import { ItemHeader } from "@/components/items/item-header";
import { LinesTable } from "@/components/items/lines-table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { Schemas } from "@/lib/api/types";

const ITEM_CHAT_TOOLS = ["exceptions"] as const;

function Panes({
  detail,
  history,
}: {
  detail: Schemas["ItemDetailOut"];
  history: Schemas["HistoryOut"];
}) {
  const { active, setActive } = useHighlight();
  const { item, extraction } = detail;
  const highlights = highlightsFor(extraction.final);

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <ItemHeader item={item} lock={detail.lock} />
      <div className="grid min-w-0 gap-3 lg:grid-cols-[2fr_3fr_minmax(320px,1.4fr)]">
        <GlassPanel aria-label="Artifact" className="min-w-0 overflow-hidden">
          <PanelHeader title="Artifact" titleSize="label" />
          <PanelBody flush>
          <ArtifactViewer
            itemId={item.id}
            parts={detail.parts}
            highlights={highlights}
            activeHighlightId={active}
            onHighlightHover={setActive}
          />
          </PanelBody>
        </GlassPanel>
        <section aria-label="Extraction" className="flex min-w-0 flex-col gap-3 overflow-x-auto">
          <ExtractionTabs extraction={extraction} />
          <LinesTable lines={detail.lines} currency={item.currency} />
        </section>
        <GlassPanel as="aside" aria-label="History and chat" className="min-w-0 p-2">
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
                tools={ITEM_CHAT_TOOLS}
                title="Item assistant"
                variant="compact"
                className="h-[32rem]"
              />
            </TabsContent>
          </Tabs>
        </GlassPanel>
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
