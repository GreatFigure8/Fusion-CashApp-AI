import { MonoLabel } from "@/components/common/mono-label";
import { Pill } from "@/components/common/pill";
import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { COPY, DEFAULT_MODEL_LABEL } from "./defaults";

type ChatHeaderProps = {
  /** "Assistant" on the page; the host's title (for example "Lab assistant") when compact. */
  title: string;
  connected: boolean;
  modelLabel: string;
  /** "Acting as <name> · <role>"; omitted when the host has no identity to show. */
  actingAs?: string;
  className?: string;
};

/** The 40px mono header line. */
export function ChatHeader({ title, connected, modelLabel, actingAs, className }: ChatHeaderProps) {
  return (
    <header
      className={cn(
        "flex h-10 shrink-0 items-center gap-3 border-b border-line px-4 text-[11.75px] uppercase tracking-wider",
        className,
      )}
    >
      <MonoLabel as="h2" className="text-foreground">
        {title}
      </MonoLabel>
      <Pill tone={connected ? "ok" : "warn"} dot mono>
        {connected ? "Connected" : "Reconnecting"}
      </Pill>
      <MonoLabel className="text-soft">{`${modelLabel || DEFAULT_MODEL_LABEL} · zero retention`}</MonoLabel>
      {actingAs ? <MonoLabel className="ml-auto text-soft">{actingAs}</MonoLabel> : null}
    </header>
  );
}

type ChatStatusProps =
  | { kind: "error"; code: string; message: string; onRetry: () => void }
  | { kind: "disconnected"; onRetry: () => void };

/** Error and dropped-connection banner with Retry. */
export function ChatStatus(props: ChatStatusProps) {
  const body =
    props.kind === "disconnected"
      ? COPY.disconnected
      : props.code === "TIMEOUT" || props.code === "timeout"
        ? COPY.timeout
        : `${props.message} ${COPY.nothingChanged}`;
  return (
    <div data-slot="chat-status">
      <StateCard
        kind="error"
        label={props.kind === "error" ? `Error · ${props.code}` : "Error · disconnected"}
        headline={body}
        actions={
          <Button type="button" variant="outline" size="sm" aria-label="Retry" onClick={props.onRetry}>
            Retry
          </Button>
        }
      />
    </div>
  );
}
