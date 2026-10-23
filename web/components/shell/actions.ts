"use server";

import { z } from "zod";

import { apiAction } from "@/lib/api/actions";
import { api } from "@/lib/api/client";
import type { Schemas } from "@/lib/api/types";
import { err, ok } from "@/lib/result";
import { apiError } from "@/lib/api/errors";
import { getSession } from "@/lib/auth/session";

const searchSchema = z.object({ q: z.string().trim().min(1).max(100) });

export type SearchHit = Schemas["SearchHitOut"];

/** The ⌘K palette's lookup: items by WI id, receipt number or invoice number. */
export const searchItems = apiAction(searchSchema, async ({ q }) => {
  // Authentication is checked here as well as in proxy.ts and the API.
  if (!(await getSession())) {
    return err(apiError(401, "session_expired", "Your session has expired. Sign in again.", null));
  }
  const result = await api("get", "/search", { query: { q } });
  if (!result.ok) return result;
  return ok(result.value.hits);
});
