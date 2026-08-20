import { useQuery } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext } from "react";

import type { components } from "./control.generated";
import type { ControlClient } from "./control-client";

type Session = components["schemas"]["SessionView"];

interface ControlContextValue {
  client: ControlClient;
  session: Session;
}

interface ControlProviderProps {
  children: ReactNode;
  client: ControlClient;
  loadingFallback?: ReactNode;
}

export const sessionQueryKey = ["control", "session"] as const;

const ControlContext = createContext<ControlContextValue | null>(null);

export function ControlProvider({
  children,
  client,
  loadingFallback = null,
}: ControlProviderProps) {
  const sessionQuery = useQuery({
    queryKey: sessionQueryKey,
    queryFn: ({ signal }) => client.bootstrapSession(signal),
    staleTime: Number.POSITIVE_INFINITY,
  });

  if (sessionQuery.isPending) {
    return loadingFallback;
  }
  if (sessionQuery.isError) {
    throw sessionQuery.error;
  }

  return (
    <ControlContext.Provider value={{ client, session: sessionQuery.data }}>
      {children}
    </ControlContext.Provider>
  );
}

export function useControl(): ControlContextValue {
  const value = useContext(ControlContext);
  if (value === null) {
    throw new Error("useControl must be used within ControlProvider");
  }
  return value;
}

export function useControlSession(): Session {
  return useControl().session;
}
