"use client";

import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { Segmented } from "@/components/common/segmented";
import { UI_WINDOWS, type DashboardWindow } from "@/lib/metrics/schemas";

const OPTIONS = UI_WINDOWS.map((value) => ({ value, label: value }));

/** Changes `?window=`, so every tile is fetched again on the server. */
export function WindowControl({ value }: { value: DashboardWindow }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <div data-pending={pending ? "true" : undefined} className="data-[pending=true]:opacity-60">
      <Segmented
        options={OPTIONS}
        value={value}
        ariaLabel="Time window"
        onChange={(next) =>
          startTransition(() => {
            router.replace(`?window=${next}`, { scroll: false });
          })
        }
      />
    </div>
  );
}
