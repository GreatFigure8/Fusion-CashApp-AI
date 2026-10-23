"use client";

import { useState } from "react";
import { PlusIcon, XIcon } from "lucide-react";

import { DropZone, type RejectedFile } from "@/components/common/drop-zone";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

import { uploadStageSchema } from "./chat-schemas";
import { DEFAULT_UPLOADS } from "./defaults";

export type StagedUpload = { id: string; name: string };

export type UploadLimits = {
  maxBytes: number;
  maxFiles: number;
  accept: readonly string[];
};

type AttachProps = {
  staged: readonly StagedUpload[];
  onStaged: (added: readonly StagedUpload[]) => void;
  onRemove: (id: string) => void;
  limits?: UploadLimits;
  disabled?: boolean;
};

const STAGE_URL = "/api/review/uploads?stage_only=true";

async function stage(files: readonly File[]): Promise<StagedUpload[] | string> {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  try {
    const res = await fetch(STAGE_URL, { method: "POST", body: form });
    if (!res.ok) return "The upload was refused.";
    const parsed = uploadStageSchema.safeParse(await res.json());
    if (!parsed.success) return "The upload returned an unexpected answer.";
    return parsed.data.upload_ids.map((id, i) => ({ id, name: files[i]?.name ?? id }));
  } catch {
    return "The upload could not be sent.";
  }
}

/** The `+` button: stages images for the next turn through the review upload proxy. */
export function Attach({ staged, onStaged, onRemove, limits = DEFAULT_UPLOADS, disabled }: AttachProps) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const room = Math.max(0, limits.maxFiles - staged.length);

  const onFiles = async (files: readonly File[], rejected: readonly RejectedFile[]) => {
    setProblem(rejected.length > 0 ? `${rejected.length} file(s) were not accepted.` : null);
    if (files.length === 0) return;
    setBusy(true);
    const result = await stage(files.slice(0, room));
    setBusy(false);
    if (typeof result === "string") setProblem(result);
    else onStaged(result);
  };

  return (
    <div className="flex items-center gap-2">
      <Popover>
        <PopoverTrigger
          render={
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Attach images"
              disabled={disabled || busy || room === 0}
            >
              <PlusIcon />
            </Button>
          }
        />
        <PopoverContent side="top" align="start" className="w-80">
          <DropZone
            variant="inline"
            accept={limits.accept}
            maxBytes={limits.maxBytes}
            maxFiles={room}
            disabled={busy}
            title="Drop receipt images"
            onFiles={(files, rejected) => void onFiles(files, rejected)}
          />
          {problem ? (
            <p role="alert" className="mt-2 text-xs text-err">
              {problem}
            </p>
          ) : null}
        </PopoverContent>
      </Popover>
      {staged.length > 0 ? (
        <ul aria-label="Staged images" className="flex flex-wrap gap-1.5">
          {staged.map((s) => (
            <li
              key={s.id}
              className="inline-flex items-center gap-1 rounded-full border border-line bg-surface-3 px-2 py-0.5 font-mono text-[11px]"
            >
              <span className="max-w-32 truncate">{s.name}</span>
              <button type="button" aria-label={`Remove ${s.name}`} onClick={() => onRemove(s.id)}>
                <XIcon aria-hidden="true" className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
