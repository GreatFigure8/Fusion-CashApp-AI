import { DiffBlock } from "@/components/common/diff-block";
import { GlassPanel, PanelBody, PanelHeader } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";
import { Pill } from "@/components/common/pill";
import { formatDuration } from "@/lib/format";
import { diffLines, type LabCandidate, type LabReplay } from "@/lib/lab/view";

/** The candidate, its config diff against live and (when replayed) how the replay went. */
export function CandidateCard({
  candidate,
  replay,
}: {
  candidate: LabCandidate;
  replay: LabReplay | null;
}) {
  const complete = replay?.status === "DONE";
  return (
    <GlassPanel aria-label={`Candidate ${candidate.id}`}>
      <PanelHeader title={`Candidate ${candidate.id} vs live v${candidate.live_version}`}>
        {complete ? (
          <MonoLabel>
            Replay complete
            {replay.duration_ms !== null
              ? ` · ${formatDuration(replay.duration_ms / 1000)}`
              : ""}
          </MonoLabel>
        ) : null}
        {replay ? (
          <Pill tone="muted">
            {replay.total} items · {replay.window_days} days
          </Pill>
        ) : null}
        {candidate.status === "PROMOTED" ? (
          <Pill tone="ok">
            Promoted{candidate.promoted_version !== null ? ` · live v${candidate.promoted_version}` : ""}
          </Pill>
        ) : null}
        {candidate.status === "DISCARDED" ? <Pill tone="muted">Discarded</Pill> : null}
      </PanelHeader>
      <PanelBody className="grid gap-3">
        {candidate.rationale ? (
          <p className="text-[13px] text-muted-foreground">{candidate.rationale}</p>
        ) : null}
        <DiffBlock lines={diffLines(candidate.config_diff)} caption="Config changes vs live" />
      </PanelBody>
    </GlassPanel>
  );
}
