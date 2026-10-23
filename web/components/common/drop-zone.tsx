"use client";

import { UploadIcon } from "lucide-react";
import { useId, useRef, useState, type DragEvent, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type RejectedFile = {
  readonly file: File;
  readonly reason: "too_large" | "not_allowed" | "too_many";
};

export type DropZoneProps = {
  /** MIME types, for example `["image/png", "image/jpeg", "image/webp", "application/pdf"]`. */
  accept: readonly string[];
  maxBytes: number;
  maxFiles: number;
  onFiles: (files: readonly File[], rejected: readonly RejectedFile[]) => void;
  disabled?: boolean;
  title?: string;
  hint?: string;
  /** `inline` is the compact target used by the chat composer. */
  variant?: "panel" | "inline";
};

/** A browser pre-check for a nicer message. The API re-checks everything: it is the control. */
export function sortFiles(
  incoming: readonly File[],
  { accept, maxBytes, maxFiles }: Pick<DropZoneProps, "accept" | "maxBytes" | "maxFiles">,
): { files: File[]; rejected: RejectedFile[] } {
  const files: File[] = [];
  const rejected: RejectedFile[] = [];
  for (const file of incoming) {
    if (!accept.includes(file.type)) rejected.push({ file, reason: "not_allowed" });
    else if (file.size > maxBytes) rejected.push({ file, reason: "too_large" });
    else if (files.length >= maxFiles) rejected.push({ file, reason: "too_many" });
    else files.push(file);
  }
  return { files, rejected };
}

/** The one place files are dropped or picked. Everything that takes a file imports this. */
export function DropZone({
  accept,
  maxBytes,
  maxFiles,
  onFiles,
  disabled = false,
  title = "Drop failed receipt images",
  hint,
  variant = "panel",
}: DropZoneProps): React.JSX.Element {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const inline = variant === "inline";

  const receive = (list: FileList | null) => {
    if (disabled || list === null || list.length === 0) return;
    const sorted = sortFiles(Array.from(list), { accept, maxBytes, maxFiles });
    onFiles(sorted.files, sorted.rejected);
  };

  const onDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setOver(false);
    receive(event.dataTransfer.files);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      inputRef.current?.click();
    }
  };

  return (
    <div
      data-slot="drop-zone"
      data-over={over ? "true" : undefined}
      role="group"
      aria-label={title}
      aria-disabled={disabled || undefined}
      tabIndex={disabled ? -1 : 0}
      onKeyDown={onKeyDown}
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={cn(
        "flex flex-col items-center gap-2.5 rounded-2xl border-[1.5px] border-dashed text-center transition-colors",
        "border-line-strong bg-brand-soft/30",
        over && "border-primary bg-brand-soft",
        disabled && "pointer-events-none opacity-60",
        inline ? "flex-row justify-center gap-3 px-3 py-2" : "p-8",
      )}
    >
      <UploadIcon aria-hidden className={cn("text-brand-ink", inline ? "size-4" : "size-8")} />
      <span className={cn("font-semibold", inline ? "text-sm" : "text-[17px]")}>{title}</span>
      {hint && !inline ? <span className="text-[13px] text-muted-foreground">{hint}</span> : null}
      <Button
        type="button"
        variant="outline"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        Choose files
      </Button>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        multiple
        accept={accept.join(",")}
        disabled={disabled}
        className="sr-only"
        tabIndex={-1}
        aria-label="Choose files"
        onChange={(event) => {
          receive(event.currentTarget.files);
          event.currentTarget.value = "";
        }}
      />
    </div>
  );
}
