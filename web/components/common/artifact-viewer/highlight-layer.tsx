"use client";

import { cn } from "@/lib/utils";

export type ArtifactHighlight = {
  id: string;
  label: string;
  partNo: number;
  page: number | null;
  bbox: { x: number; y: number; w: number; h: number } | null;
  quote: string | null;
};

/** Boxes drawn over one page or image as percentages of its size, so they scale with it. */
export function HighlightLayer({
  highlights,
  activeId,
  onHover,
}: {
  highlights: ArtifactHighlight[];
  activeId: string | null | undefined;
  onHover?: (id: string | null) => void;
}) {
  return (
    <div data-slot="highlight-layer" className="pointer-events-none absolute inset-0">
      {highlights.map((highlight) => {
        const box = highlight.bbox;
        if (!box) return null;
        const active = highlight.id === activeId;
        return (
          <div
            key={highlight.id}
            data-highlight-id={highlight.id}
            data-active={active ? "true" : undefined}
            title={highlight.label}
            onMouseEnter={() => onHover?.(highlight.id)}
            onMouseLeave={() => onHover?.(null)}
            className={cn(
              "pointer-events-auto absolute rounded-[2px] border transition-colors",
              active
                ? "z-10 border-2 border-status-progress bg-status-progress/30"
                : "border-status-waiting bg-status-waiting/15 hover:bg-status-waiting/30",
            )}
            style={{
              left: `${box.x * 100}%`,
              top: `${box.y * 100}%`,
              width: `${box.w * 100}%`,
              height: `${box.h * 100}%`,
            }}
          />
        );
      })}
    </div>
  );
}
