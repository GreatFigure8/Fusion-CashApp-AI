"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { useFlowStream } from "@/components/shell/flow-stream";
import type { Schemas } from "@/lib/api/types";
import { loadReviewResult, refreshReviewQueue } from "@/app/(shell)/review/actions";

import { QueueTable } from "./queue-table";
import { ResultPanel, type ResultState } from "./result-panel";
import type { UploadResult } from "./schemas";
import { UploadPanel, type UploadLimits } from "./upload-panel";

type QueueRow = Schemas["ReviewQueueRowOut"];

const REFETCH_DEBOUNCE_MS = 1_000;

/**
 * Owns the Review board: the selected item, the queue and its result. It refetches on the shared
 * flow stream (one connection per tab, opened by the shell), never on a timer.
 */
export function ReviewBoard({
  initialRows,
  limits,
  canWork,
}: {
  initialRows: readonly QueueRow[];
  limits: UploadLimits;
  canWork: boolean;
}): React.JSX.Element {
  const router = useRouter();
  const { subscribeItemChanged } = useFlowStream();
  const [rows, setRows] = useState<readonly QueueRow[]>(initialRows);
  const [selectedId, setSelectedId] = useState<number | null>(initialRows[0]?.item_id ?? null);
  const [result, setResult] = useState<ResultState>(
    initialRows[0] ? { kind: "loading" } : { kind: "none" },
  );
  const rowsRef = useRef(rows);
  const selectedRef = useRef(selectedId);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    rowsRef.current = rows;
    selectedRef.current = selectedId;
  }, [rows, selectedId]);

  const loadResult = useCallback(async (itemId: number) => {
    const loaded = await loadReviewResult(itemId);
    if (selectedRef.current !== itemId) return; // the person moved on
    setResult(loaded.ok ? { kind: "ready", result: loaded.value } : { kind: "error", error: loaded.error });
  }, []);

  const reloadQueue = useCallback(async () => {
    const loaded = await refreshReviewQueue();
    if (loaded.ok) setRows(loaded.value.items);
  }, []);

  useEffect(() => {
    if (selectedId === null) return;
    void loadResult(selectedId);
  }, [selectedId, loadResult]);

  useEffect(
    () =>
      subscribeItemChanged((event) => {
        const isQueued = rowsRef.current.some((row) => row.item_id === event.id);
        if (!isQueued) return;
        clearTimeout(timer.current);
        timer.current = setTimeout(() => {
          void reloadQueue();
          if (selectedRef.current === event.id) void loadResult(event.id);
        }, REFETCH_DEBOUNCE_MS);
      }),
    [subscribeItemChanged, reloadQueue, loadResult],
  );

  useEffect(() => () => clearTimeout(timer.current), []);

  const select = (itemId: number) => {
    setResult({ kind: "loading" });
    setSelectedId(itemId);
  };

  const onSubmitted = (uploaded: UploadResult) => {
    router.refresh(); // the top bar's "Today N / M uploads" is rendered on the server
    void reloadQueue();
    const first = uploaded.files.find((f) => f.status === "STORED" && f.item_id !== null);
    if (first?.item_id != null) select(first.item_id);
  };

  const selected = rows.find((row) => row.item_id === selectedId);

  return (
    <div className="flex flex-col gap-4">
      <UploadPanel limits={limits} canWork={canWork} onSubmitted={onSubmitted} />
      <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,400px),1fr))] items-start gap-4">
        <QueueTable rows={rows} selectedId={selectedId} onSelect={select} />
        <ResultPanel itemId={selectedId} filename={selected?.filename ?? null} state={result} />
      </div>
    </div>
  );
}
