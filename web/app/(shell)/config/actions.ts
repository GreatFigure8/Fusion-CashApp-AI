"use server";

import { refresh } from "next/cache";
import { z } from "zod";

import { apiAction } from "@/lib/api/actions";
import { reasonSchema } from "@/components/config/config-schemas";
import { ok } from "@/lib/result";

import { runMcpTest } from "./_lib/mcp-test";
import { setSecretValue } from "./_lib/set-secret";
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

// A connection test changes no setting, so there is nothing to refresh.
const mcpTest = apiAction(z.object({}), async () => runMcpTest());

const secretInput = z.object({
  name: z.string().trim().min(1).max(120),
  value: z.string().min(1).max(16384),
  reason: reasonSchema,
});

// A secret is not a setting row, so there is no version to refresh; the value never comes back.
const secret = apiAction(secretInput, async ({ name, value, reason }) =>
  setSecretValue(name, value, reason),
);

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

export async function testMcpConnection(input: unknown) {
  return mcpTest(input);
}

export async function setSecret(input: unknown) {
  return secret(input);
}
