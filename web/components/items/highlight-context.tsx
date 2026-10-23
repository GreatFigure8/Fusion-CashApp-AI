"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

type HighlightValue = { active: string | null; setActive: (id: string | null) => void };

const HighlightContext = createContext<HighlightValue | null>(null);

/** Links the extraction rows (middle pane) to the highlight boxes (left pane). */
export function HighlightProvider({ children }: { children: ReactNode }) {
  const [active, setActive] = useState<string | null>(null);
  const value = useMemo(() => ({ active, setActive }), [active]);
  return <HighlightContext.Provider value={value}>{children}</HighlightContext.Provider>;
}

export function useHighlight(): HighlightValue {
  const value = useContext(HighlightContext);
  if (value === null) throw new Error("useHighlight must be used inside HighlightProvider");
  return value;
}
