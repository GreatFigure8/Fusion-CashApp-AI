import { notFound } from "next/navigation";
import { z } from "zod";

import { ErrorAlert } from "@/components/common/error-alert";
import { RequirePermission } from "@/components/common/require-permission";
import { TopBar } from "@/components/shell/top-bar";
import { StageItemsTable } from "@/components/flow/stage-items-table";
import { api } from "@/lib/api/client";
import { humanizeEnum } from "@/lib/format";
import { getMe } from "@/lib/me";

const paramsSchema = z.object({
  stage: z
    .string()
    .regex(/^[a-z_]+$/)
    .transform((value) => value.toUpperCase()),
});

const searchSchema = z.object({
  state: z.enum(["PENDING", "IN_PROGRESS", "AWAITING_RECEIPT", "ESCALATED", "DONE", "ARCHIVED"]).optional(),
  page: z.coerce.number().int().min(1).default(1),
});

const TILES = [
  "INTAKE",
  "CLASSIFY",
  "EXTRACT",
  "ADJUDICATE",
  "VALIDATE",
  "RESOLVE_CUSTOMER",
  "FAST_PATH",
  "MATCH_RECEIPT",
  "AWAITING_RECEIPT",
  "MATCH_LINES",
  "APPLY",
  "WRITE_BACK",
  "DONE",
] as const;

export default async function StagePage({ params, searchParams }: PageProps<"/flow/[stage]">) {
  const parsedParams = paramsSchema.safeParse(await params);
  const tile = parsedParams.success
    ? TILES.find((candidate) => candidate === parsedParams.data.stage)
    : undefined;
  const parsedSearch = searchSchema.safeParse(await searchParams);
  if (!tile || !parsedSearch.success) notFound();
  const { state, page } = parsedSearch.data;

  const [me, items] = await Promise.all([
    getMe(),
    api("get", "/flow/stages/{tile}/items", { params: { tile }, query: { state, page } }),
  ]);
  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your account" />;
  if (!items.ok && (items.error.status === 404 || items.error.status === 422)) notFound();

  return (
    <RequirePermission me={me.value} permission="items:read" role="VIEWER">
      <div className="flex min-w-0 flex-col gap-3">
        <TopBar title={humanizeEnum(tile)} crumb="Flow" />
        {items.ok ? (
          <StageItemsTable
            key={`${tile}-${state ?? "all"}-${page}`}
            tile={tile}
            data={items.value}
            stateFilter={state ?? null}
          />
        ) : (
          <ErrorAlert error={items.error} title="Couldn't load this stage" />
        )}
      </div>
    </RequirePermission>
  );
}
