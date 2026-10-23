"use client";

import { FileTextIcon } from "lucide-react";
import { Meter } from "@/components/common/meter";
import { Pill } from "@/components/common/pill";

import { formatBytes, uploadPill, type ThumbState } from "./format";

/** One chosen file: preview, name, size, a 4px progress meter and its status pill. */
export function UploadThumb({
  file,
  previewUrl,
  state,
  maxBytes,
}: {
  file: File;
  /** An object URL the owner creates on add and revokes on remove. */
  previewUrl: string | null;
  state: ThumbState;
  maxBytes: number;
}): React.JSX.Element {
  const pill = uploadPill(state, maxBytes);
  const value = state.kind === "uploading" ? state.progress : state.kind === "result" && state.status === "STORED" ? 1 : 0;
  const meterTone = state.kind === "uploading" ? "accent" : pill.tone === "ok" ? "ok" : pill.tone === "err" ? "err" : "accent";

  return (
    <li
      data-slot="upload-thumb"
      className="flex flex-col overflow-hidden rounded-xl border border-line bg-white/[0.02]"
    >
      <div className="flex h-28 items-center justify-center bg-surface-2" aria-hidden>
        {previewUrl !== null ? (
          // eslint-disable-next-line @next/next/no-img-element -- a local object URL, never optimised
          <img src={previewUrl} alt="" className="size-full object-cover" />
        ) : (
          <FileTextIcon className="size-8 text-muted-foreground" />
        )}
      </div>
      <div className="flex flex-col gap-1.5 px-3 py-2.5">
        <span className="truncate text-[13px]" title={file.name}>
          {file.name}
        </span>
        <span className="font-mono text-[11px] text-muted-foreground">{formatBytes(file.size)}</span>
        <Meter value={value} tone={meterTone} size={5} label={`Upload progress for ${file.name}`} />
        <Pill tone={pill.tone} className="self-start text-[11.5px]">
          {pill.label}
        </Pill>
      </div>
    </li>
  );
}
