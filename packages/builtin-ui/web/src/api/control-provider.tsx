import { useQuery } from "@tanstack/react-query";
import { createContext, type ReactNode, useContext } from "react";
import { useEffect, useRef, useState } from "react";
import { Button, Center, Stack, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { ControlFailure } from "./control-client";
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
  const { i18n, t } = useTranslation();
  const recoveredFromError = useRef(false);
  const retryInFlight = useRef(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const sessionQuery = useQuery({
    queryKey: sessionQueryKey,
    queryFn: ({ signal }) => client.bootstrapSession(signal),
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Number.POSITIVE_INFINITY,
  });

  useEffect(() => {
    if (sessionQuery.data === undefined) {
      document.documentElement.lang = i18n.resolvedLanguage ?? "en";
      document.title = t("appName");
    }
  }, [i18n, t, sessionQuery.data]);

  useEffect(() => {
    if (sessionQuery.isError) {
      recoveredFromError.current = true;
      return;
    }
    if (sessionQuery.isSuccess && recoveredFromError.current) {
      recoveredFromError.current = false;
      document.querySelector<HTMLElement>("main")?.focus();
    }
  }, [sessionQuery.isError, sessionQuery.isSuccess]);

  if (sessionQuery.isPending && !recoveredFromError.current) {
    return loadingFallback;
  }
  if (
    sessionQuery.isError ||
    (recoveredFromError.current && sessionQuery.isFetching)
  ) {
    const code =
      sessionQuery.error instanceof ControlFailure
        ? sessionQuery.error.code
        : "unexpected_response";
    return (
      <Center mih="100vh" p="md">
        <Stack
          component="section"
          maw={560}
          role="alert"
          style={{ minWidth: 0, overflowWrap: "anywhere" }}
        >
          <Title order={1}>{t("bootstrap.title")}</Title>
          <Text>
            {t(`errors.${code}`, {
              defaultValue: t("errors.unexpected_response"),
            })}
          </Text>
          {sessionQuery.isFetching || isRetrying ? (
            <Text role="status">{t("recovery.loading")}</Text>
          ) : null}
          <Button
            onClick={() => {
              if (retryInFlight.current) return;
              retryInFlight.current = true;
              setIsRetrying(true);
              void sessionQuery.refetch().finally(() => {
                retryInFlight.current = false;
                setIsRetrying(false);
              });
            }}
            loading={sessionQuery.isFetching || isRetrying}
            disabled={sessionQuery.isFetching || isRetrying}
          >
            {t("recovery.retry")}
          </Button>
        </Stack>
      </Center>
    );
  }

  const session = sessionQuery.data;
  if (session === undefined) {
    return loadingFallback;
  }

  return (
    <ControlContext.Provider value={{ client, session }}>
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
