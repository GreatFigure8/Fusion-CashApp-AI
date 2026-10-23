"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { Me } from "@/lib/permissions";

export type ShellSession = {
  readonly me: Me;
  readonly env: Me["env"];
  readonly sampleData: boolean;
};

const ShellSessionContext = createContext<ShellSession | null>(null);

/** Puts the signed-in user and environment facts in context, once, for the whole shell. */
export function ShellSessionProvider({
  me,
  env,
  sampleData,
  children,
}: {
  me: Me;
  env: Me["env"];
  sampleData: boolean;
  children: ReactNode;
}) {
  const value = useMemo<ShellSession>(() => ({ me, env, sampleData }), [me, env, sampleData]);
  return <ShellSessionContext.Provider value={value}>{children}</ShellSessionContext.Provider>;
}

export function useShellSession(): ShellSession {
  const value = useContext(ShellSessionContext);
  if (value === null) throw new Error("useShellSession must be used inside the shell");
  return value;
}
