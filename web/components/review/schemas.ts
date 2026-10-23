import { z } from "zod";

/** The upload response, parsed where it enters the browser. */
export const uploadFileResultSchema = z.object({
  filename: z.string(),
  status: z.enum(["STORED", "DUPLICATE", "TOO_LARGE", "NOT_ALLOWED", "QUOTA"]),
  item_id: z.number().int().nullable(),
  message: z.string(),
});

export const quotaSchema = z.object({ used: z.number().int(), limit: z.number().int() });

export const uploadResultSchema = z.object({
  files: z.array(uploadFileResultSchema),
  quota: quotaSchema,
});

export type UploadFileResult = z.infer<typeof uploadFileResultSchema>;
export type UploadResult = z.infer<typeof uploadResultSchema>;

/** The API's single error shape, as the proxy forwards it. */
export const errorEnvelopeSchema = z.object({
  error: z.object({ code: z.string(), message: z.string() }),
});
