import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** DEV, TEST or PROD from `NEXT_PUBLIC_ENV_LABEL`; PROD gets a red outline. */
export function EnvBadge({ label }: { label: string }) {
  const prod = label.toUpperCase() === "PROD";
  return (
    <Badge
      variant="outline"
      data-env={label}
      className={cn("font-mono", prod && "border-status-error text-status-error")}
    >
      {label}
    </Badge>
  );
}
