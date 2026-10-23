/** The API streaming paths the web proxy may forward. Adding a stream means editing this list. */
export const STREAM_PATHS = ["/flow/stream", "/chat/stream"] as const;

/** Streams whose path carries an id. Each entry is a whole-path regex. */
export const STREAM_PATH_PATTERNS = [/^\/chat\/tool-calls\/[A-Za-z0-9_-]{1,64}\/confirm$/] as const;

export type StreamPath = (typeof STREAM_PATHS)[number] | `/chat/tool-calls/${string}/confirm`;

export function isStreamPath(p: string): p is StreamPath {
  return (
    (STREAM_PATHS as readonly string[]).includes(p) || STREAM_PATH_PATTERNS.some((re) => re.test(p))
  );
}
