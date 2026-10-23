import "server-only";

import { cache } from "react";

import { api } from "@/lib/api/client";
import type { ApiError } from "@/lib/api/errors";
import type { Result } from "@/lib/result";

import type { Me } from "./permissions";

export { hasPermission, ROUTE_PERMISSIONS } from "./permissions";
export type { Me };

/** One `/me` call per request, however many server components ask. */
export const getMe: () => Promise<Result<Me, ApiError>> = cache(() => api("get", "/me"));
