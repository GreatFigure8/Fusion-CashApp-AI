import { notFound } from "next/navigation";
import { z } from "zod";

import { ErrorAlert } from "@/components/common/error-alert";
import { RequirePermission } from "@/components/common/require-permission";
import { ItemView } from "@/components/items/item-view";
import { api } from "@/lib/api/client";
import { parseWorkItemId } from "@/lib/format";
import { getMe } from "@/lib/me";

const paramsSchema = z.object({
  id: z.string().refine((value) => parseWorkItemId(value) !== null),
});

export default async function ItemPage({ params }: PageProps<"/items/[id]">) {
  const parsed = paramsSchema.safeParse(await params);
  const id = parsed.success ? parseWorkItemId(parsed.data.id) : null;
  if (id === null) notFound();

  const [me, detail, history] = await Promise.all([
    getMe(),
    api("get", "/items/{item_id}", { params: { item_id: id } }),
    api("get", "/items/{item_id}/history", { params: { item_id: id } }),
  ]);
  if (!me.ok) return <ErrorAlert error={me.error} title="Couldn't load your account" />;
  if (!detail.ok && detail.error.status === 404) notFound();
  if (!detail.ok) return <ErrorAlert error={detail.error} title="Couldn't load this item" />;
  if (!history.ok) return <ErrorAlert error={history.error} title="Couldn't load this item's history" />;

  return (
    <RequirePermission me={me.value} permission="items:read" role="VIEWER">
      <ItemView detail={detail.value} history={history.value} />
    </RequirePermission>
  );
}
