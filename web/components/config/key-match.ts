/** Edit distance between two strings (insert, delete, substitute each cost 1). */
export function levenshtein(a: string, b: string): number {
  if (a === b) return 0;
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i += 1) {
    const row = [i];
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a.charCodeAt(i - 1) === b.charCodeAt(j - 1) ? 0 : 1;
      row[j] = Math.min((prev[j] ?? 0) + 1, (row[j - 1] ?? 0) + 1, (prev[j - 1] ?? 0) + cost);
    }
    prev = row;
  }
  return prev[b.length] ?? 0;
}

/** Lower-case words of a key, split on `.` and `_`. */
export function keyTokens(key: string): readonly string[] {
  return key
    .toLowerCase()
    .split(/[._]/)
    .filter((t) => t.length > 0);
}

/** Entries whose key or help text contains the query, case-insensitively. */
export function searchEntries<T extends { key: string; description: string }>(
  entries: readonly T[],
  q: string,
): T[] {
  const needle = q.trim().toLowerCase();
  if (needle === "") return [];
  return entries.filter(
    (e) => e.key.toLowerCase().includes(needle) || e.description.toLowerCase().includes(needle),
  );
}

const MAX_DISTANCE = 2;

/**
 * The closest key token or full key within distance 2 of the query, or null.
 * Ties go to the shorter candidate, then alphabetical order.
 */
export function didYouMean(q: string, keys: readonly string[]): string | null {
  const needle = q.trim().toLowerCase();
  if (needle === "") return null;
  const candidates = new Set<string>();
  for (const key of keys) {
    candidates.add(key.toLowerCase());
    for (const token of keyTokens(key)) candidates.add(token);
  }
  let best: { value: string; distance: number } | null = null;
  for (const value of candidates) {
    const distance = levenshtein(needle, value);
    if (distance > MAX_DISTANCE || distance === 0) continue;
    if (
      best === null ||
      distance < best.distance ||
      (distance === best.distance &&
        (value.length < best.value.length ||
          (value.length === best.value.length && value < best.value)))
    ) {
      best = { value, distance };
    }
  }
  return best?.value ?? null;
}
