import type { PillTone } from "@/components/common/pill";
import type { Schemas } from "@/lib/api/types";

type Source = Schemas["FieldSource"];
type UploadStatus = Schemas["UploadStatus"];

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatLimit(bytes: number): string {
  return `${Number((bytes / (1024 * 1024)).toFixed(1))} MB`;
}

export function sourcePill(source: Source): { tone: PillTone; label: string } {
  switch (source) {
    case "A_EQ_B":
      return { tone: "ok", label: "A = B" };
    case "A_B_DIFFERED":
      return { tone: "warn", label: "A, B differed" };
    case "A_ONLY":
      return { tone: "muted", label: "A only" };
    case "B_ONLY":
      return { tone: "muted", label: "B only" };
  }
}

export type ThumbState =
  | { readonly kind: "uploading"; readonly progress: number }
  | { readonly kind: "result"; readonly status: UploadStatus; readonly itemId: number | null }
  | { readonly kind: "rejected"; readonly reason: "too_large" | "not_allowed" | "too_many" }
  | { readonly kind: "ready" };

/** The pill on a thumbnail. `maxBytes` comes from the page's configuration, not a constant. */
export function uploadPill(state: ThumbState, maxBytes: number): { tone: PillTone; label: string } {
  switch (state.kind) {
    case "ready":
      return { tone: "muted", label: "Ready" };
    case "uploading":
      return { tone: "accent", label: `Uploading ${Math.round(state.progress * 100)}%` };
    case "rejected":
      if (state.reason === "too_large") return { tone: "err", label: `Over ${formatLimit(maxBytes)}` };
      if (state.reason === "too_many") return { tone: "err", label: "Too many files" };
      return { tone: "err", label: "Not an image" };
    case "result":
      switch (state.status) {
        case "STORED":
          return { tone: "ok", label: "Stored" };
        case "DUPLICATE":
          return {
            tone: "locked",
            label: state.itemId === null ? "Duplicate" : `Duplicate of WI-${state.itemId}`,
          };
        case "TOO_LARGE":
          return { tone: "err", label: `Over ${formatLimit(maxBytes)}` };
        case "NOT_ALLOWED":
          return { tone: "err", label: "Not an image" };
        case "QUOTA":
          return { tone: "err", label: "Daily limit reached" };
      }
  }
}

export function formatAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

const MIME_BY_TYPE: Readonly<Record<string, string>> = {
  png: "image/png",
  jpeg: "image/jpeg",
  webp: "image/webp",
  pdf: "application/pdf",
};
const LABEL_BY_TYPE: Readonly<Record<string, string>> = {
  png: "PNG",
  jpeg: "JPG",
  webp: "WEBP",
  pdf: "PDF",
};

export function acceptedMimeTypes(allowed: readonly string[]): string[] {
  return allowed.flatMap((type) => MIME_BY_TYPE[type] ?? []);
}

/** "PNG, JPG, WEBP or PDF · up to 5 MB each · 10 files at a time · location data is stripped". */
export function uploadHint(limits: {
  readonly allowed_types: readonly string[];
  readonly max_file_bytes: number;
  readonly max_files_per_request: number;
}): string {
  const labels = limits.allowed_types.map((type) => LABEL_BY_TYPE[type] ?? type.toUpperCase());
  const last = labels.at(-1);
  const types = labels.length > 1 ? `${labels.slice(0, -1).join(", ")} or ${last}` : (last ?? "");
  return [
    types,
    `up to ${formatLimit(limits.max_file_bytes)} each`,
    `${limits.max_files_per_request} files at a time`,
    "location data is stripped",
  ].join(" · ");
}
