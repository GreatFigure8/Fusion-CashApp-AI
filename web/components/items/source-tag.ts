import type { PillTone } from "@/components/common/pill";

/** Pure: how a provenance source (reader A, reader B, both, a person) is labelled and toned. */

export const SOURCE_TAG: Readonly<Record<string, string>> = {
  A: "A",
  B: "B",
  both: "A+B",
  human: "Human",
};

export function sourceTone(tag: string): PillTone {
  if (tag === "both") return "ok";
  if (tag === "human") return "accent";
  return "muted";
}
