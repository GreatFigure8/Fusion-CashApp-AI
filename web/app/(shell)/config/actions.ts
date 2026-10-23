"use server";

import { refresh } from "next/cache";
import { z } from "zod";

import { apiAction } from "@/lib/api/actions";
import { reasonSchema } from "@/components/config/config-schemas";
import { ok } from "@/lib/result";

import {
  purgeDryRunCall,
  retireAliasCall,
  saveInputSchema,
  saveStagedChanges,
} from "./_lib/save-config";

// A "use server" file may only export async functions, so each action is a thin async wrapper.
const save = apiAction(saveInputSchema, async (input) => {
  const out = await saveStagedChanges(input);
  if (out.results.some((r) => r.outcome === "saved")) refresh();
  return ok(out);
});

const retire = apiAction(
  z.object({ aliasId: z.number().int().positive(), reason: reasonSchema }),
  async ({ aliasId, reason }) => {
    const res = await retireAliasCall(aliasId, reason);
    if (res.ok) refresh();
    return res;
  },
);

const purge = apiAction(z.object({}), async () => purgeDryRunCall());

/** Saves the staged changes, one PUT per key. Every key's outcome comes back; the call itself succeeds. */
export async function saveConfigChanges(input: unknown) {
  return save(input);
}

export async function retireAlias(input: unknown) {
  return retire(input);
}

export async function runRetentionPurgeDryRun(input: unknown) {
  return purge(input);
}
