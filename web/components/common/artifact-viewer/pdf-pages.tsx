"use client";

import type { PDFDocumentLoadingTask, PDFDocumentProxy } from "pdfjs-dist";
import { useEffect, useRef, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";

import { HighlightLayer, type ArtifactHighlight } from "./highlight-layer";

const RENDER_SCALE = 1.5;

type LoadedDoc = { data: ArrayBuffer; doc: PDFDocumentProxy } | { data: ArrayBuffer; failed: true };

function PdfPage({
  doc,
  pageNumber,
  highlights,
  activeId,
  onHover,
}: {
  doc: PDFDocumentProxy;
  pageNumber: number;
  highlights: ArtifactHighlight[];
  activeId: string | null | undefined;
  onHover?: (id: string | null) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    let cancel: (() => void) | undefined;
    void (async () => {
      const page = await doc.getPage(pageNumber);
      const canvas = canvasRef.current;
      if (cancelled || !canvas) return;
      const viewport = page.getViewport({ scale: RENDER_SCALE });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      const task = page.render({ canvas, viewport });
      cancel = () => task.cancel();
      await task.promise.catch(() => undefined); // a cancelled render is not an error
    })();
    return () => {
      cancelled = true;
      cancel?.();
    };
  }, [doc, pageNumber]);

  const onThisPage = highlights.filter((h) => (h.page ?? 1) === pageNumber);
  return (
    <div className="relative w-full overflow-hidden rounded border bg-white" data-page={pageNumber}>
      <canvas ref={canvasRef} className="block h-auto w-full" aria-label={`Page ${pageNumber}`} />
      <HighlightLayer highlights={onThisPage} activeId={activeId} onHover={onHover} />
    </div>
  );
}

/** Renders every page of a PDF to a canvas with a highlight layer on top (pdfjs-dist). */
export function PdfPages({
  data,
  highlights,
  activeId,
  onHover,
}: {
  data: ArrayBuffer;
  highlights: ArtifactHighlight[];
  activeId: string | null | undefined;
  onHover?: (id: string | null) => void;
}) {
  const [loaded, setLoaded] = useState<LoadedDoc | null>(null);

  useEffect(() => {
    let cancelled = false;
    let task: PDFDocumentLoadingTask | undefined;
    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();
        // pdfjs transfers the buffer to its worker, so hand it a copy.
        task = pdfjs.getDocument({ data: new Uint8Array(data.slice(0)) });
        const doc = await task.promise;
        if (!cancelled) setLoaded({ data, doc });
      } catch {
        if (!cancelled) setLoaded({ data, failed: true });
      }
    })();
    return () => {
      cancelled = true;
      if (task) void task.destroy();
    };
  }, [data]);

  if (!loaded || loaded.data !== data) return <Skeleton className="h-96 w-full" />;
  if ("failed" in loaded) {
    return <p className="text-sm text-muted-foreground">This PDF couldn&apos;t be rendered.</p>;
  }
  return (
    <div className="flex flex-col gap-3">
      {Array.from({ length: loaded.doc.numPages }, (_, index) => (
        <PdfPage
          key={index + 1}
          doc={loaded.doc}
          pageNumber={index + 1}
          highlights={highlights}
          activeId={activeId}
          onHover={onHover}
        />
      ))}
    </div>
  );
}
