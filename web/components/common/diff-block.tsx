import { cn } from "@/lib/utils";

export type DiffLine = { readonly op: "-" | "+" | " "; readonly text: string };

const LINE_CLASS: Readonly<Record<DiffLine["op"], string>> = {
  "-": "bg-err-soft text-err-ink",
  "+": "bg-ok-soft text-ok-ink",
  " ": "text-muted-foreground",
};

/** A mono config diff: removed lines err-tinted, added lines ok-tinted, context plain. */
export function DiffBlock({
  lines,
  caption,
  className,
}: {
  lines: readonly DiffLine[];
  caption?: string;
  className?: string;
}) {
  return (
    <figure data-slot="diff-block" className={cn("grid gap-1.5", className)}>
      <div
        role="group"
        aria-label={caption ?? "Changes"}
        className="overflow-x-auto rounded-lg border border-line bg-log py-1 font-mono text-[12.5px]"
      >
        {lines.map((line, index) => (
          <div
            key={`${index}-${line.text}`}
            data-op={line.op}
            className={cn("flex gap-2 whitespace-pre px-3 py-0.5", LINE_CLASS[line.op])}
          >
            <span aria-hidden className="w-3 shrink-0 select-none">
              {line.op === " " ? "" : line.op}
            </span>
            <span>{line.text}</span>
          </div>
        ))}
      </div>
      {caption ? (
        <figcaption className="text-xs text-muted-foreground">{caption}</figcaption>
      ) : null}
    </figure>
  );
}
