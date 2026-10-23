import "server-only";

import { z } from "zod";

export { publicEnv } from "./env.public";

export const serverEnvSchema = z.object({
  OIDC_ISSUER: z.string().url(),
  OIDC_CLIENT_ID: z.string().min(1),
  OIDC_CLIENT_SECRET: z.string().min(1),
  SESSION_SECRET: z.string().min(32),
  API_BASE_URL: z.string().url(),
  APP_BASE_URL: z.string().url(),
});

export type ServerEnv = z.infer<typeof serverEnvSchema>;

/** Names only, never values: the message is safe to log. */
export class EnvError extends Error {
  readonly missing: string[];
  readonly invalid: string[];

  constructor(missing: string[], invalid: string[]) {
    const parts: string[] = [];
    if (missing.length > 0) parts.push(`missing ${missing.join(", ")}`);
    if (invalid.length > 0) parts.push(`invalid ${invalid.join(", ")}`);
    super(`Invalid environment: ${parts.join("; ")}`);
    this.name = "EnvError";
    this.missing = missing;
    this.invalid = invalid;
  }
}

export function parseServerEnv(
  source: Record<string, string | undefined>,
): ServerEnv {
  const result = serverEnvSchema.safeParse(source);
  if (result.success) return result.data;

  const missing = new Set<string>();
  const invalid = new Set<string>();
  for (const issue of result.error.issues) {
    const name = String(issue.path[0] ?? "");
    if (name === "") continue;
    const value = source[name];
    if (value === undefined || value === "") missing.add(name);
    else invalid.add(name);
  }
  throw new EnvError([...missing], [...invalid]);
}

let cached: Readonly<ServerEnv> | undefined;

function load(): Readonly<ServerEnv> {
  cached ??= Object.freeze(parseServerEnv(process.env));
  return cached;
}

/** Validates process.env once; call at boot so a bad configuration fails fast. */
export function assertServerEnv(): void {
  load();
}

/** Lazily validated on first property access, then frozen. */
export const serverEnv: Readonly<ServerEnv> = new Proxy({} as ServerEnv, {
  get: (_target, prop) => Reflect.get(load(), prop),
  has: (_target, prop) => Reflect.has(load(), prop),
  ownKeys: () => Reflect.ownKeys(load()),
  getOwnPropertyDescriptor: (_target, prop) =>
    Reflect.getOwnPropertyDescriptor(load(), prop),
});
