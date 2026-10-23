import { z } from "zod";

const DEFAULT_RETURN_TO = "/";

// Relative, same-origin paths only. Rejects protocol-relative ("//host"), backslash tricks,
// control characters and the auth endpoints themselves (a redirect loop).
const returnToSchema = z
  .string()
  .min(1)
  .max(2048)
  .refine(
    (value) =>
      value.startsWith("/") &&
      !value.startsWith("//") &&
      !value.includes("\\") &&
      !/[\u0000-\u001f\u007f]/.test(value) &&
      !value.startsWith("/auth/"),
    { message: "returnTo must be a relative path" },
  );

export function parseReturnTo(value: unknown): string {
  const parsed = returnToSchema.safeParse(value);
  return parsed.success ? parsed.data : DEFAULT_RETURN_TO;
}
