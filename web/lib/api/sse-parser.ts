export type SseFrame = {
  id: string | null;
  event: string;
  data: string;
  retry: number | null;
};

/** Incremental parser for the WHATWG event-stream format. Pure: no I/O, safe on the client. */
export function createSseParser(onFrame: (f: SseFrame) => void): {
  push(chunk: string): void;
  flush(): void;
} {
  let buffer = "";
  let lastId: string | null = null;
  let retry: number | null = null;
  let event = "";
  let data: string[] = [];

  function dispatch(): void {
    if (data.length > 0) {
      onFrame({ id: lastId, event: event === "" ? "message" : event, data: data.join("\n"), retry });
    }
    event = "";
    data = [];
  }

  function line(text: string): void {
    if (text === "") return dispatch();
    if (text.startsWith(":")) return;
    const colon = text.indexOf(":");
    const field = colon === -1 ? text : text.slice(0, colon);
    let value = colon === -1 ? "" : text.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    switch (field) {
      case "event":
        event = value;
        break;
      case "data":
        data.push(value);
        break;
      case "id":
        if (!value.includes("\0")) lastId = value;
        break;
      case "retry":
        if (/^\d+$/.test(value)) retry = Number(value);
        break;
      default:
        break;
    }
  }

  function drain(final: boolean): void {
    let start = 0;
    for (let i = 0; i < buffer.length; i += 1) {
      const ch = buffer[i];
      if (ch === "\n" || ch === "\r") {
        if (ch === "\r" && i === buffer.length - 1 && !final) break; // might be CRLF split
        line(buffer.slice(start, i));
        if (ch === "\r" && buffer[i + 1] === "\n") i += 1;
        start = i + 1;
      }
    }
    buffer = buffer.slice(start);
  }

  return {
    push(chunk: string): void {
      buffer += chunk;
      drain(false);
    },
    flush(): void {
      drain(true);
      if (buffer !== "") line(buffer);
      buffer = "";
      dispatch();
    },
  };
}
