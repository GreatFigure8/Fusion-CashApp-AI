import { z } from "zod";

/** First value of a search param; an unknown or malformed value falls back to the default. */
const first = (v: unknown): unknown => (Array.isArray(v) ? v[0] : v);

export const ALIASES_GROUP = "aliases";

export const searchSchema = z.object({
  group: z.preprocess(first, z.string().regex(/^[a-z0-9_-]{1,64}$/).optional().catch(undefined)),
  q: z.preprocess(first, z.string().trim().max(100).catch("")).default(""),
  history: z.preprocess(first, z.string().regex(/^[a-z0-9_.]{1,100}$/).optional().catch(undefined)),
  aq: z.preprocess(first, z.string().trim().max(200).catch("")).default(""),
  apage: z.preprocess(first, z.coerce.number().int().min(1).catch(1)).default(1),
});

export type ConfigSearch = z.infer<typeof searchSchema>;

/** The requested group when the API knows it (or it is the aliases link); otherwise the first group. */
export function resolveGroup(
  requested: string | undefined,
  groups: readonly { group: string }[],
): string {
  if (requested === ALIASES_GROUP) return ALIASES_GROUP;
  const known = groups.find((g) => g.group === requested);
  return known?.group ?? groups[0]?.group ?? ALIASES_GROUP;
}
