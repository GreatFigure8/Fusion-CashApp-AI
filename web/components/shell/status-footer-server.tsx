import { StatusFooter } from "@/components/shell/status-footer";
import { buildApiRequest, send } from "@/lib/api/client";
import { engineStatusSchema, type EngineStatus } from "@/lib/engine/status";

/** `GET /engine/status`, Zod-parsed at the boundary. Any failure yields null (never throws). */
async function readEngineStatus(): Promise<EngineStatus | null> {
  const prepared = await buildApiRequest("get", "/engine/status", "application/json", {});
  if (!prepared.ok) return null;
  const sent = await send(prepared.value);
  if (!sent.ok || !sent.value.ok) return null;
  try {
    const parsed = engineStatusSchema.safeParse(await sent.value.json());
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

/** Streams in on its own Suspense boundary, so a slow bus read never blocks the shell. */
export async function StatusFooterServer() {
  return <StatusFooter initial={await readEngineStatus()} />;
}
