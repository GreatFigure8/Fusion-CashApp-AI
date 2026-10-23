import type * as React from "react";

import { buttonVariants } from "@/components/ui/button";

type Target =
  | Readonly<{ report: "daily-summary"; date: string }>
  | Readonly<{ report: "partially-paid"; from: string; to: string }>;

function href(target: Target, format: "csv" | "xlsx"): string {
  const q = new URLSearchParams({ format });
  if (target.report === "daily-summary") q.set("date", target.date);
  else {
    q.set("from", target.from);
    q.set("to", target.to);
  }
  return `/api/reports/${target.report}/export?${q.toString()}`;
}

export function ExportButtons({ target }: { target: Target }): React.JSX.Element {
  return (
    <>
      <a
        href={href(target, "csv")}
        download
        className={buttonVariants({ variant: "outline" })}
      >
        Export CSV
      </a>
      <a
        href={href(target, "xlsx")}
        download
        className={buttonVariants({ variant: "outline" })}
      >
        Export XLSX
      </a>
    </>
  );
}
