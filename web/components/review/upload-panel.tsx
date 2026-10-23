"use client";

import { useEffect, useRef, useState } from "react";

import { ActionButton } from "@/components/common/action-button";
import { DropZone, type RejectedFile } from "@/components/common/drop-zone";
import { GlassPanel, PanelBody } from "@/components/common/glass-panel";
import { StateCard } from "@/components/common/state-card";
import { Button } from "@/components/ui/button";

import { acceptedMimeTypes, formatLimit, uploadHint, type ThumbState } from "./format";
import { errorEnvelopeSchema, uploadResultSchema, type UploadResult } from "./schemas";
import { UploadThumb } from "./upload-thumb";

export type UploadLimits = {
  readonly allowed_types: readonly string[];
  readonly max_file_bytes: number;
  readonly max_files_per_request: number;
};

type Entry = {
  readonly id: number;
  readonly file: File;
  readonly previewUrl: string | null;
  readonly state: ThumbState;
};

const previewOf = (file: File): string | null =>
  file.type.startsWith("image/") ? URL.createObjectURL(file) : null;

const revoke = (entries: readonly Entry[]) => {
  for (const e of entries) if (e.previewUrl !== null) URL.revokeObjectURL(e.previewUrl);
};

type SendResult =
  | { readonly ok: true; readonly value: UploadResult }
  | { readonly ok: false; readonly message: string };

/** XMLHttpRequest because `fetch` has no upload progress. Parsed with Zod where it enters. */
function sendFiles(files: readonly File[], onProgress: (fraction: number) => void): Promise<SendResult> {
  return new Promise((resolve) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/review/uploads");
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onerror = () => resolve({ ok: false, message: "The upload could not reach the server." });
    xhr.onload = () => {
      let json: unknown = null;
      try {
        json = JSON.parse(xhr.responseText);
      } catch {
        json = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        const parsed = uploadResultSchema.safeParse(json);
        resolve(
          parsed.success
            ? { ok: true, value: parsed.data }
            : { ok: false, message: "The server sent a response we could not read." },
        );
        return;
      }
      const envelope = errorEnvelopeSchema.safeParse(json);
      resolve({
        ok: false,
        message: envelope.success ? envelope.data.error.message : `The upload failed (${xhr.status}).`,
      });
    };
    xhr.send(form);
  });
}

function rejectedMessage(reason: RejectedFile["reason"], name: string, maxBytes: number, maxFiles: number) {
  switch (reason) {
    case "too_large":
      return { headline: `${name} is over ${formatLimit(maxBytes)}`, body: "Crop or compress it and add it again." };
    case "too_many":
      return { headline: `${name} was not added`, body: `Only ${maxFiles} files fit in one submission.` };
    case "not_allowed":
      return { headline: `${name} is not an accepted file`, body: "Use a PNG, JPG, WEBP or PDF file." };
  }
}

export function UploadPanel({
  limits,
  canWork,
  onSubmitted,
}: {
  limits: UploadLimits;
  canWork: boolean;
  onSubmitted: (result: UploadResult) => void;
}): React.JSX.Element {
  const [entries, setEntries] = useState<readonly Entry[]>([]);
  const [nextId, setNextId] = useState(1);
  const [problem, setProblem] = useState<{ headline: string; body: string; entryId: number | null } | null>(null);
  const [busy, setBusy] = useState(false);

  const latest = useRef<readonly Entry[]>(entries);
  useEffect(() => {
    latest.current = entries;
  }, [entries]);
  useEffect(() => () => revoke(latest.current), []);

  const accept = acceptedMimeTypes(limits.allowed_types);
  const ready = entries.filter((e) => e.state.kind === "ready");

  const addFiles = (files: readonly File[], rejected: readonly RejectedFile[]) => {
    let id = nextId;
    const added: Entry[] = files.map((file) => ({
      id: id++,
      file,
      previewUrl: previewOf(file),
      state: { kind: "ready" },
    }));
    const refused: Entry[] = rejected.map(({ file, reason }) => ({
      id: id++,
      file,
      previewUrl: null,
      state: { kind: "rejected", reason },
    }));
    setNextId(id);
    setEntries((current) => [...current, ...added, ...refused]);
    const first = refused[0];
    if (first && first.state.kind === "rejected") {
      const text = rejectedMessage(first.state.reason, first.file.name, limits.max_file_bytes, limits.max_files_per_request);
      setProblem({ ...text, entryId: first.id });
    } else {
      setProblem(null);
    }
  };

  const submit = async () => {
    const sending = ready;
    if (sending.length === 0 || busy) return;
    const ids = new Set(sending.map((e) => e.id));
    setBusy(true);
    setProblem(null);
    const setStates = (make: (entry: Entry, index: number) => ThumbState) =>
      setEntries((current) => {
        let index = 0;
        return current.map((e) => (ids.has(e.id) ? { ...e, state: make(e, index++) } : e));
      });
    setStates(() => ({ kind: "uploading", progress: 0 }));
    const result = await sendFiles(sending.map((e) => e.file), (progress) =>
      setStates(() => ({ kind: "uploading", progress })),
    );
    setBusy(false);
    if (!result.ok) {
      setStates(() => ({ kind: "ready" }));
      setProblem({ headline: "The upload didn't finish", body: `${result.message} Your files were kept.`, entryId: null });
      return;
    }
    const outcome = result.value.files;
    setStates((_entry, index) => {
      const file = outcome[index];
      return file
        ? { kind: "result", status: file.status, itemId: file.item_id }
        : { kind: "ready" };
    });
    const failed = outcome.find((f) => f.status === "TOO_LARGE" || f.status === "NOT_ALLOWED" || f.status === "QUOTA");
    if (failed) {
      setProblem({ headline: failed.message, body: "The other files were kept.", entryId: null });
    }
    onSubmitted(result.value);
  };

  const remove = (id: number | null) => {
    if (id !== null) {
      revoke(entries.filter((e) => e.id === id));
      setEntries((current) => current.filter((e) => e.id !== id));
    }
    setProblem(null);
  };

  return (
    <GlassPanel aria-label="Upload failed receipts">
      <PanelBody className="flex flex-col gap-4">
        <DropZone
          accept={accept}
          maxBytes={limits.max_file_bytes}
          maxFiles={limits.max_files_per_request}
          onFiles={addFiles}
          disabled={!canWork || busy}
          hint={uploadHint(limits)}
        />
        {!canWork ? (
          <p className="text-[13px] text-muted-foreground">Uploading needs items:work.</p>
        ) : null}
        {problem !== null ? (
          <StateCard
            kind="error"
            label="Error · upload"
            headline={problem.headline}
            body={problem.body}
            actions={
              <Button type="button" variant="outline" onClick={() => remove(problem.entryId)}>
                {problem.entryId === null ? "Dismiss" : "Remove file"}
              </Button>
            }
          />
        ) : null}
        {entries.length > 0 ? (
          <ul className="grid list-none grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3 p-0">
            {entries.map((entry) => (
              <UploadThumb key={entry.id} file={entry.file} previewUrl={entry.previewUrl} state={entry.state} maxBytes={limits.max_file_bytes} />
            ))}
          </ul>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={entries.length === 0 || busy}
            onClick={() => {
              revoke(entries);
              setEntries([]);
              setProblem(null);
            }}
          >
            Clear
          </Button>
          <ActionButton
            type="button"
            glow
            disabled={!canWork || ready.length === 0 || busy}
            onClick={() => void submit()}
          >
            Submit {ready.length} for in-depth review
          </ActionButton>
        </div>
      </PanelBody>
    </GlassPanel>
  );
}
