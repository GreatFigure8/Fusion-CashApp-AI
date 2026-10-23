"use client";

import {
  createContext,
  useContext,
  useMemo,
  useReducer,
  type Dispatch,
  type ReactNode,
} from "react";

import {
  initialStagingState,
  stagingReducer,
  type StagingAction,
  type StagingState,
} from "./staging";

type StagingContextValue = Readonly<{
  state: StagingState;
  dispatch: Dispatch<StagingAction>;
  canEdit: boolean;
}>;

const StagingContext = createContext<StagingContextValue | null>(null);

/** Holds staged edits for every tab. Wraps the tabs, panel and footer, so edits survive tab switches. */
export function ConfigStagingProvider({
  canEdit,
  children,
}: {
  canEdit: boolean;
  children: ReactNode;
}) {
  const [state, dispatch] = useReducer(stagingReducer, initialStagingState);
  const value = useMemo(() => ({ state, dispatch, canEdit }), [state, canEdit]);
  return <StagingContext.Provider value={value}>{children}</StagingContext.Provider>;
}

export function useStaging(): StagingContextValue {
  const ctx = useContext(StagingContext);
  if (!ctx) throw new Error("useStaging must be used inside ConfigStagingProvider");
  return ctx;
}
