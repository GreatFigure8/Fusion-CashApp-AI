import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import { DISCONNECTED_COPY, TIMEOUT_COPY } from "./defaults";

type ChatStatusProps =
  | { kind: "error"; code: string; message: string; onRetry: () => void }
  | { kind: "disconnected"; onRetry: () => void };

export function ChatStatus(props: ChatStatusProps) {
  const text =
    props.kind === "disconnected"
      ? DISCONNECTED_COPY
      : props.code === "timeout"
        ? TIMEOUT_COPY
        : `${props.message} Try again`;
  return (
    <Alert variant={props.kind === "error" ? "destructive" : "default"} data-slot="chat-status">
      <AlertDescription className="flex items-center justify-between gap-2">
        <span>{text}</span>
        <Button type="button" variant="outline" size="sm" aria-label="Retry" onClick={props.onRetry}>
          Retry
        </Button>
      </AlertDescription>
    </Alert>
  );
}
