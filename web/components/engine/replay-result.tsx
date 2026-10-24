import type { Schemas } from "@/lib/api/types";

import { Pill } from "@/components/common/pill";

/** After a replay: how many went back through, and which were skipped and why. */
export function ReplayResult({
  result,
  replayedIds,
}: Readonly<{ result: Schemas["ReplayOut"]; replayedIds: readonly string[] }>) {
  const skipped = new Set(result.skipped.map((s) => s.event_id));
  const replayed = replayedIds.filter((id) => !skipped.has(id));
  return (
    <div className="grid gap-2 text-sm" role="status">
      <p>
        <Pill tone="ok">Replayed {result.replayed}</Pill>
      </p>
      <ul className="font-mono text-xs">
        {replayed.map((id) => (
          <li key={id}>{id}</li>
        ))}
      </ul>
      {result.skipped.length > 0 ? (
        <>
          <p>
            <Pill tone="warn">Skipped {result.skipped.length}</Pill>
          </p>
          <ul className="font-mono text-xs text-soft">
            {result.skipped.map((s) => (
              <li key={s.event_id}>
                {s.event_id} — {s.why}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}
