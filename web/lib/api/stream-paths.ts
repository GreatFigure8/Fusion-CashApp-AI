/**
 * The API streaming paths the web proxy may forward. Adding a stream means appending to this
 * list. A `:name` segment matches exactly one non-empty `[A-Za-z0-9_-]+` segment.
 */
export const STREAM_PATHS = [
  "/flow/stream",
  "/chat/stream",
  "/engine/stream",
  "/metrics/stream",
  "/chat/tool-calls/:id/confirm",
] as const;

type ExpandParams<P extends string> = P extends `${infer Head}:${string}/${infer Tail}`
  ? `${Head}${string}/${ExpandParams<Tail>}`
  : P extends `${infer Head}:${string}`
    ? `${Head}${string}`
    : P;

export type StreamPath = ExpandParams<(typeof STREAM_PATHS)[number]>;

const SEGMENT = /^[A-Za-z0-9_-]+$/;

function matches(pattern: string, path: string): boolean {
  const want = pattern.split("/");
  const got = path.split("/");
  if (want.length !== got.length) return false;
  return want.every((segment, i) => {
    const actual = got[i] ?? "";
    return segment.startsWith(":") ? SEGMENT.test(actual) : segment === actual;
  });
}

export function isStreamPath(p: string): p is StreamPath {
  return (STREAM_PATHS as readonly string[]).some((pattern) => matches(pattern, p));
}
