import { z } from "zod";

export const publicEnvSchema = z.object({
  NEXT_PUBLIC_ENV_LABEL: z.string().default("LOCAL"),
});

export type PublicEnv = z.infer<typeof publicEnvSchema>;

// Reads the literal process.env.NEXT_PUBLIC_ENV_LABEL so Next inlines it into client bundles.
export const publicEnv: Readonly<PublicEnv> = Object.freeze(
  publicEnvSchema.parse({
    NEXT_PUBLIC_ENV_LABEL: process.env.NEXT_PUBLIC_ENV_LABEL,
  }),
);
