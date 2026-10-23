import { cn } from "@/lib/utils";

/** Shimmering placeholder rows shaped like content, with an optional caption of what is read. */
export function SkeletonRows({
  rows = 3,
  height = 12,
  caption,
  className,
}: {
  rows?: number;
  height?: number;
  caption?: string;
  className?: string;
}) {
  return (
    <div
      aria-busy="true"
      data-slot="skeleton-rows"
      className={cn("grid gap-2.5", className)}
    >
      {Array.from({ length: rows }, (_, index) => (
        <div
          key={index}
          data-slot="skeleton-row"
          className="animate-shimmer rounded-md bg-[linear-gradient(90deg,#ffffff08,#ffffff14,#ffffff08)] bg-[length:200%_100%] motion-reduce:animate-none"
          style={{ height }}
        />
      ))}
      {caption ? <p className="text-xs text-muted-foreground">{caption}</p> : null}
    </div>
  );
}
