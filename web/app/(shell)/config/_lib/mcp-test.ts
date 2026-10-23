import "server-only";

import { api } from "@/lib/api/client";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import { err, ok, type Result } from "@/lib/result";

import type { ApiCaller } from "./save-config";

/** Runs the fusion-sql-mcp connection test. The API reports server failures in `error`, not as 5xx. */
export async function runMcpTest(
  call: ApiCaller = api,
): Promise<Result<Schemas["McpTestOut"], ApiError>> {
  const res = await call("post", "/integrations/mcp/test");
  return res.ok ? ok(res.value) : err(res.error);
}
