import "server-only";

import { unstable_rethrow } from "next/navigation";
import type { z } from "zod";

import { err, type Result } from "@/lib/result";

import { apiError, type ApiError } from "./errors";

async function guarded<T>(run: () => Promise<Result<T, ApiError>>): Promise<Result<T, ApiError>> {
  try {
    return await run();
  } catch (e) {
    unstable_rethrow(e); // redirect() and notFound() must pass through
    // Name only, never the message: it may carry remittance content.
    console.error(
      JSON.stringify({
        level: "error",
        message: "apiAction failed",
        name: e instanceof Error ? e.name : "unknown",
      }),
    );
    return err(apiError(500, "internal_error", "Something went wrong.", null));
  }
}

/**
 * Wraps a server-action body so it always returns plain, serialisable data.
 * With a schema, the input is validated first and a failure becomes a 422 `validation_error`.
 */
export function apiAction<A extends unknown[], T>(
  fn: (...args: A) => Promise<Result<T, ApiError>>,
): (...args: A) => Promise<Result<T, ApiError>>;
export function apiAction<S extends z.ZodType, T>(
  schema: S,
  fn: (input: z.infer<S>) => Promise<Result<T, ApiError>>,
): (input: unknown) => Promise<Result<T, ApiError>>;
export function apiAction(
  first: unknown,
  second?: (input: unknown) => Promise<Result<unknown, ApiError>>,
): (...args: never[]) => Promise<Result<unknown, ApiError>> {
  if (typeof first === "function") {
    const fn = first as (...args: unknown[]) => Promise<Result<unknown, ApiError>>;
    return (...args: never[]) => guarded(() => fn(...args));
  }
  const schema = first as z.ZodType;
  const fn = second as (input: unknown) => Promise<Result<unknown, ApiError>>;
  return (input: never) => {
    const parsed = schema.safeParse(input);
    if (!parsed.success) {
      return Promise.resolve(
        err(
          apiError(
            422,
            "validation_error",
            "Some fields are invalid.",
            null,
            parsed.error.issues.map((i) => ({ path: i.path.join("."), message: i.message })),
          ),
        ),
      );
    }
    return guarded(() => fn(parsed.data));
  };
}
