import "server-only";

import { ALIAS_PAGE_SIZE } from "@/components/config/aliases-panel";
import { GROUP_ROLE_KEY } from "@/components/config/config-registry";
import { api } from "@/lib/api/client";
import type { ApiError } from "@/lib/api/errors";
import { getMe } from "@/lib/me";
import type { Result } from "@/lib/result";
import type { Schemas } from "@/lib/api/types";

export const HISTORY_PAGE_SIZE = 50;

export function loadMe(): Promise<Result<Schemas["MeResponse"], ApiError>> {
  return getMe();
}

export function loadConfigEntries(): Promise<Result<Schemas["ConfigEntry"][], ApiError>> {
  return api("get", "/config");
}

export function loadGroupRoles(): Promise<Result<Schemas["GroupRolesResponse"], ApiError>> {
  return api("get", "/access/group-roles");
}

/** The newest change to the group-role map; `GET /access/group-roles` carries only the subject. */
export function loadLatestGroupRolesChange(): Promise<Result<Schemas["ConfigChangePage"], ApiError>> {
  return api("get", "/access/group-roles/history", { query: { limit: 1 } });
}

export function loadAliases(args: {
  q: string | undefined;
  page: number;
}): Promise<Result<Schemas["AliasPage"], ApiError>> {
  return api("get", "/aliases", {
    query: {
      active: true,
      q: args.q || undefined,
      offset: (args.page - 1) * ALIAS_PAGE_SIZE,
      limit: ALIAS_PAGE_SIZE,
    },
  });
}

export function loadHistory(key: string): Promise<Result<Schemas["ConfigChangePage"], ApiError>> {
  if (key === GROUP_ROLE_KEY) {
    return api("get", "/access/group-roles/history", { query: { limit: HISTORY_PAGE_SIZE } });
  }
  return api("get", "/config/{key}/history", {
    params: { key },
    query: { limit: HISTORY_PAGE_SIZE },
  });
}
