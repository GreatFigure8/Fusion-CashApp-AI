/** The API streaming paths the web proxy may forward. Adding a stream means editing this list. */
export const STREAM_PATHS = ["/flow/stream", "/chat/stream", "/engine/stream"] as const;

export type StreamPath = (typeof STREAM_PATHS)[number];

export function isStreamPath(p: string): p is StreamPath {
  return (STREAM_PATHS as readonly string[]).includes(p);
}
