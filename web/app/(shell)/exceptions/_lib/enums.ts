import "server-only";

import openapi from "@/lib/api/openapi.json";

import type { ErrorCode, Stage } from "./search-params";

/** Option lists for the filter bar, read from the generated OpenAPI document (one source of truth). */
export const ERROR_CODES = openapi.components.schemas.ErrorCode.enum as readonly ErrorCode[];
export const STAGES = openapi.components.schemas.Stage.enum as readonly Stage[];
