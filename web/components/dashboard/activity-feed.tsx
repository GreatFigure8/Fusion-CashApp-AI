import type { Route } from "next";
import Link from "next/link";

import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { Pill, type PillTone } from "@/components/common/pill";
import type { StreamStatus } from "@/hooks/use-event-stream";
import type { Schemas } from "@/lib/api/types";
import { formatClock } from "@/lib/metrics/format";

type Event = Schemas["ActivityEvent"];

const KIND: Record<Event["kind"], { label: string; tone: PillTone }> = {
  APPLIED: { label: "Applied", tone: "ok" },
  RECEIPT_ARRIVED: { label: "Receipt arrived", tone: "accent" },
  AUTOFIX: { label: "Auto-fix", tone: "warn" },
  ESCALATED: { label: "Escalated", tone: "err" },
};

function StreamPill({ status, ageSeconds }: { status: StreamStatus; ageSeconds: number | null }) {
  if (status === "live") {
    return (
      <Pill tone="ok" dot pulse mono>
        {ageSeconds === null ? "Streaming" : `Streaming · ${ageSeconds}s ago`}
      </Pill>
    );
  }
  if (status === "reconnecting") {
    return (
      <Pill tone="warn" dot mono>
        Reconnecting…
      </Pill>
    );
  }
  return (
    <Pill tone="muted" mono>
      Stream paused
    </Pill>
  );
}

export function ActivityFeed({
  events,
  status,
  ageSeconds,
}: {
  events: readonly Event[];
  status: StreamStatus;
  ageSeconds: number | null;
}) {
  return (
    <GlassPanel as="section" aria-label="Live activity">
      <PanelHeader title="Live activity">
        <StreamPill status={status} ageSeconds={ageSeconds} />
      </PanelHeader>
      <PanelBody flush>
        {events.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">No activity yet.</p>
        ) : (
          <ol className="max-h-80 divide-y divide-white/5 overflow-y-auto">
            {events.map((event) => {
              const kind = KIND[event.kind];
              return (
                <li
                  key={`${event.kind}:${event.id}`}
                  className="flex items-center gap-3 px-4 py-2 text-sm"
                >
                  <time dateTime={event.at} className="font-mono text-xs text-muted-foreground">
                    {formatClock(event.at)}
                  </time>
                  <Pill tone={kind.tone}>{kind.label}</Pill>
                  {event.item_id === null ? (
                    <span className="min-w-0 truncate">{event.text}</span>
                  ) : (
                    <Link
                      href={`/items/${event.item_id}` as Route}
                      className="min-w-0 truncate hover:underline"
                    >
                      {event.text}
                    </Link>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </PanelBody>
    </GlassPanel>
  );
}
