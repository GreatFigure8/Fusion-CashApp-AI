import "server-only";

import { api } from "@/lib/api/client";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import { err, ok, type Result } from "@/lib/result";

import type { ApiCaller } from "./save-config";

/** Stores a secret's value (encrypted by the API). The value goes in and is never returned. */
export async function setSecretValue(
  name: string,
  value: string,
  reason: string,
  call: ApiCaller = api,
): Promise<Result<Schemas["SecretOut"], ApiError>> {
  const res = await call("put", "/secrets/{name}", { params: { name }, body: { value, reason } });
  return res.ok ? ok(res.value) : err(res.error);
}
