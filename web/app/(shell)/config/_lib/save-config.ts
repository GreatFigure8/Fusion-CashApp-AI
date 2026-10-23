import "server-only";

import { z } from "zod";

import {
  groupRolesSchema,
  jsonValueSchema,
  reasonSchema,
} from "@/components/config/config-schemas";
import { saveOrder } from "@/components/config/config-registry";
import { fieldErrorsFromLoc, type KeyResult } from "@/components/config/staging";
import { api } from "@/lib/api/client";
import type { ApiError } from "@/lib/api/errors";
import { err, ok, type Result } from "@/lib/result";
import type { Schemas } from "@/lib/api/types";

/** The API caller, injectable so unit tests can run these functions against a mock server. */
export type ApiCaller = typeof api;

export const saveInputSchema = z
  .object({
    reason: reasonSchema,
    changes: z.array(
      z.object({
        key: z.string().min(1),
        value: jsonValueSchema,
        expected_version: z.number().int().min(0),
      }),
    ),
    groupRoles: z.object({ mappings: groupRolesSchema }).optional(),
  })
  .refine((v) => v.changes.length > 0 || v.groupRoles !== undefined, {
    message: "Nothing to save.",
  });
export type SaveInput = z.infer<typeof saveInputSchema>;

function detailNumber(error: ApiError, name: string): number | null {
  const value = error.details[0]?.[name];
  return typeof value === "number" ? value : null;
}

/** One key's API error as a per-key result. */
function resultForError(key: string, error: ApiError): KeyResult {
  if (error.status === 409 && error.code === "config_conflict") {
    return {
      key,
      outcome: "conflict",
      currentVersion: detailNumber(error, "current_version"),
      message: "This setting was changed by someone else since you opened it.",
    };
  }
  if (error.status === 422 && error.code === "invalid_config_value") {
    return {
      key,
      outcome: "invalid",
      fieldErrors: fieldErrorsFromLoc(error.details),
      message: error.message,
    };
  }
  if (error.status === 422 && error.code === "last_admin_mapping") {
    return {
      key,
      outcome: "invalid",
      fieldErrors: [{ path: "", message: error.message }],
      message: error.message,
    };
  }
  return { key, outcome: "failed", error };
}

/**
 * Saves each changed key with its own PUT, one after another in registry order, so results are
 * deterministic. The group-role map goes last. One key failing never stops the others.
 */
export async function saveStagedChanges(
  input: SaveInput,
  call: ApiCaller = api,
): Promise<{ results: KeyResult[] }> {
  const results: KeyResult[] = [];
  const ordered = [...input.changes].sort((a, b) => saveOrder(a.key) - saveOrder(b.key));
  for (const change of ordered) {
    const res = await call("put", "/config/{key}", {
      params: { key: change.key },
      body: {
        value: change.value,
        reason: input.reason,
        expected_version: change.expected_version,
      },
    });
    results.push(
      res.ok
        ? { key: change.key, outcome: "saved", version: res.value.version }
        : resultForError(change.key, res.error),
    );
  }
  if (input.groupRoles) {
    const key = "access.group_role_map";
    const res = await call("put", "/access/group-roles", {
      body: { mappings: input.groupRoles.mappings, reason: input.reason },
    });
    results.push(
      res.ok ? { key, outcome: "saved", version: 0 } : resultForError(key, res.error),
    );
  }
  return { results };
}

export async function retireAliasCall(
  aliasId: number,
  reason: string,
  call: ApiCaller = api,
): Promise<Result<Schemas["AliasOut"], ApiError>> {
  const res = await call("post", "/aliases/{alias_id}/retire", {
    params: { alias_id: aliasId },
    body: { reason },
  });
  return res.ok ? ok(res.value) : err(res.error);
}

/** A real purge is out of scope: this can only ever send `dry_run: true`. */
export async function purgeDryRunCall(
  call: ApiCaller = api,
): Promise<Result<Schemas["PurgeReportResponse"], ApiError>> {
  const res = await call("post", "/admin/retention/purge", { body: { dry_run: true } });
  return res.ok ? ok(res.value) : err(res.error);
}
