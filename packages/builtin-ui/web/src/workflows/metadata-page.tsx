import {
  Button,
  Fieldset,
  Group,
  Loader,
  Modal,
  Paper,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { components } from "../api/control.generated";
import { ControlFailure } from "../api/control-client";
import { useControl } from "../api/control-provider";
import styles from "./metadata-page.module.css";

type SearchResult = components["schemas"]["MetadataSearchResult"];
type MediaItem = components["schemas"]["MediaItemDetail"];
type Locale = components["schemas"]["Locale"];

function ResultPoster({ result }: { result: SearchResult }) {
  const { t } = useTranslation();
  const [failed, setFailed] = useState(false);
  if (result.poster_url === null || result.poster_url === undefined || failed) {
    return (
      <div
        aria-label={t("metadata.posterUnavailable", { title: result.title })}
        className={styles.poster}
        data-poster-fallback="true"
        role="img"
      >
        <span aria-hidden="true">MF</span>
      </div>
    );
  }
  return (
    <div className={styles.poster}>
      <img
        alt={t("metadata.posterFor", { title: result.title })}
        loading="lazy"
        onError={() => setFailed(true)}
        referrerPolicy="no-referrer"
        src={result.poster_url}
      />
    </div>
  );
}

function ResultRow({
  disabled,
  feedbackCode,
  onSelect,
  pending,
  result,
}: {
  disabled: boolean;
  feedbackCode: string | null;
  onSelect: () => void;
  pending: boolean;
  result: SearchResult;
}) {
  const { t } = useTranslation();
  const selectionStatus = t("metadata.selecting", { title: result.title });
  return (
    <Paper
      aria-label={`${result.title}${result.year ? ` (${result.year})` : ""}`}
      className={styles.resultRow}
      component="article"
      p="sm"
      withBorder
    >
      <ResultPoster result={result} />
      <Stack className={styles.resultContent} gap="xs">
        <Group gap="xs" wrap="wrap">
          <Title className={styles.resultTitle} order={3} size="h4">
            {result.title}
          </Title>
          {result.year !== null && result.year !== undefined && (
            <Text c="dimmed" size="sm">
              {result.year}
            </Text>
          )}
          <Text c="dimmed" size="sm">
            {t(`mediaKind.${result.kind}`)}
          </Text>
        </Group>
        {result.description !== null && result.description !== undefined && (
          <Text className={styles.description} size="sm">
            {result.description}
          </Text>
        )}
        {pending && (
          <Text aria-label={selectionStatus} role="status" size="sm">
            {selectionStatus}
          </Text>
        )}
        {feedbackCode !== null && (
          <Text role="alert" size="sm">
            {t(`errors.${feedbackCode}`, {
              defaultValue: t("errors.unexpected_response"),
            })}
          </Text>
        )}
      </Stack>
      <Button
        className={styles.selectButton}
        disabled={disabled}
        loading={pending}
        onClick={onSelect}
      >
        {t("metadata.select")}
      </Button>
    </Paper>
  );
}

export function MetadataPage() {
  const { client, session } = useControl();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [savedItem, setSavedItem] = useState<MediaItem | null>(null);
  const [feedbackCode, setFeedbackCode] = useState<string | null>(null);
  const [selectionFeedback, setSelectionFeedback] = useState<{
    code: string;
    token: string;
  } | null>(null);
  const [confirmationToken, setConfirmationToken] = useState<string | null>(
    null,
  );
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [mode, setMode] = useState<"provider" | null>(null);
  const selectionInFlight = useRef(false);
  const searchInFlight = useRef(false);
  const providerRetryInFlight = useRef(false);
  const providerRetryButton = useRef<HTMLButtonElement>(null);
  const searchRetryButton = useRef<HTMLButtonElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const providerRetryRestoreFocus = useRef(false);
  const searchRetryRestoreFocus = useRef(false);
  const failedSearch = useRef<{ query: string; locale: Locale } | null>(null);
  const mounted = useRef(true);
  const [searchOutcome, setSearchOutcome] = useState<
    "initial" | "pending" | "success" | "empty" | "error"
  >("initial");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [providerRetryPending, setProviderRetryPending] = useState(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const providersQuery = useQuery({
    enabled: mode === "provider",
    queryKey: ["control", "metadata-providers", session.ui_locale],
    queryFn: ({ signal }) => client.listMetadataProviders(signal),
    refetchOnMount: false,
    refetchOnReconnect: false,
    refetchOnWindowFocus: false,
    retry: false,
  });
  const searchMutation = useMutation({
    mutationFn: ({
      query: submitted,
      locale,
    }: {
      query: string;
      locale: Locale;
    }) => client.searchMetadata(submitted, locale),
    retry: false,
    onMutate: ({ query: submitted }) => {
      searchInFlight.current = true;
      setSubmittedQuery(submitted);
      setSearchOutcome("pending");
      setResults([]);
      setSelectionFeedback(null);
      setFeedbackCode(null);
      setSavedItem(null);
      setConfirmationToken(null);
      setConfirmationOpen(false);
    },
    onSuccess: (values) => {
      if (!mounted.current) return;
      setResults(values);
      setFeedbackCode(null);
      setSelectionFeedback(null);
      setSavedItem(null);
      failedSearch.current = null;
      setSearchOutcome(values.length === 0 ? "empty" : "success");
    },
    onError: (error, variables) => {
      if (!mounted.current) return;
      failedSearch.current = variables;
      const code =
        error instanceof ControlFailure ? error.code : "unexpected_response";
      setFeedbackCode(code);
      setSearchOutcome("error");
    },
    onSettled: () => {
      searchInFlight.current = false;
    },
  });
  const selectionMutation = useMutation({
    mutationFn: ({
      confirmSimilarity,
      token,
    }: {
      confirmSimilarity: boolean;
      token: string;
    }) => client.selectMetadata(token, confirmSimilarity),
    onSuccess: async (item) => {
      setConfirmationOpen(false);
      setSavedItem(item);
      setFeedbackCode(null);
      setSelectionFeedback(null);
      setConfirmationToken(null);
      await queryClient.invalidateQueries({ queryKey: ["control", "catalog"] });
    },
    onError: (error, variables) => {
      if (
        error instanceof ControlFailure &&
        error.code === "confirmation_required" &&
        error.confirmationToken !== null
      ) {
        setConfirmationToken(error.confirmationToken);
        setConfirmationOpen(true);
        return;
      }
      const code =
        error instanceof ControlFailure ? error.code : "unexpected_response";
      if (code === "selection_expired") {
        setFeedbackCode(code);
        setResults([]);
        setSelectionFeedback(null);
        setConfirmationToken(null);
        setConfirmationOpen(false);
        return;
      }
      setSelectionFeedback({ code, token: variables.token });
    },
    onSettled: () => {
      selectionInFlight.current = false;
    },
  });

  const selectResult = (token: string, confirmSimilarity = false) => {
    if (selectionInFlight.current || searchInFlight.current) return;
    selectionInFlight.current = true;
    setSelectionFeedback(null);
    selectionMutation.mutate({ confirmSimilarity, token });
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    if (
      !searchInFlight.current &&
      !selectionInFlight.current &&
      query.trim().length > 0
    ) {
      searchInFlight.current = true;
      searchRetryRestoreFocus.current = false;
      searchMutation.mutate({
        query: query.trim(),
        locale: session.metadata_locale,
      });
    }
  };
  const retrySearch = () => {
    if (
      !searchInFlight.current &&
      !selectionInFlight.current &&
      failedSearch.current !== null
    ) {
      searchInFlight.current = true;
      searchRetryRestoreFocus.current =
        document.activeElement === searchRetryButton.current;
      searchMutation.mutate(failedSearch.current);
    }
  };
  const retryProviders = () => {
    if (providerRetryInFlight.current) return;
    providerRetryInFlight.current = true;
    providerRetryRestoreFocus.current =
      document.activeElement === providerRetryButton.current;
    setProviderRetryPending(true);
    void providersQuery.refetch().finally(() => {
      providerRetryInFlight.current = false;
      if (mounted.current) setProviderRetryPending(false);
    });
  };
  const availableProviders =
    providersQuery.data?.filter(
      (provider) => provider.ready && provider.capabilities.includes("search"),
    ) ?? [];
  useEffect(() => {
    if (
      !providerRetryRestoreFocus.current ||
      providerRetryPending ||
      availableProviders.length === 0
    )
      return;
    providerRetryRestoreFocus.current = false;
    if (document.activeElement === document.body) searchInput.current?.focus();
  }, [availableProviders.length, providerRetryPending]);
  useEffect(() => {
    if (
      !searchRetryRestoreFocus.current ||
      (searchOutcome !== "success" && searchOutcome !== "empty")
    )
      return;
    searchRetryRestoreFocus.current = false;
    if (document.activeElement === document.body) searchInput.current?.focus();
  }, [searchOutcome]);
  const providerKeys = Array.from(
    new Set(results.map((result) => result.provider_key)),
  );

  if (mode === null) {
    return (
      <Stack gap="lg">
        <Title order={1}>{t("routes.add")}</Title>
        <Text>{t("metadata.choosePath")}</Text>
        <Group>
          <Button onClick={() => setMode("provider")}>
            {t("metadata.chooseProvider")}
          </Button>
          <Button
            className={styles.manualButton}
            classNames={{ label: styles.manualButtonLabel }}
            color="blue.8"
            component={Link}
            to="/add/manual"
            variant="outline"
          >
            {t("metadata.chooseManual")}
          </Button>
        </Group>
      </Stack>
    );
  }

  if (providersQuery.isError || providerRetryPending) {
    const providerErrorCode =
      providersQuery.error instanceof ControlFailure
        ? providersQuery.error.code
        : "unexpected_response";
    return (
      <Stack gap="lg">
        <Title order={1}>{t("routes.add")}</Title>
        <Text className={styles.feedback} role="alert">
          {t("metadata.providersFailed")}:{" "}
          {t(`errors.${providerErrorCode}`, {
            defaultValue: t("errors.unexpected_response"),
          })}
        </Text>
        <Group>
          <Button
            aria-disabled={providerRetryPending}
            color="blue.8"
            onClick={retryProviders}
            ref={providerRetryButton}
          >
            {t("recovery.retry")}
          </Button>
          <Button
            className={styles.manualButton}
            classNames={{ label: styles.manualButtonLabel }}
            color="blue.8"
            component={Link}
            to="/add/manual"
            variant="outline"
          >
            {t("metadata.chooseManual")}
          </Button>
        </Group>
        {providerRetryPending && (
          <Text role="status">{t("recovery.loading")}</Text>
        )}
      </Stack>
    );
  }
  if (providersQuery.isPending) {
    return (
      <Stack gap="lg">
        <Title order={1}>{t("routes.add")}</Title>
        <Group gap="sm">
          <Loader aria-hidden="true" size="sm" />
          <Text role="status">{t("metadata.providersLoading")}</Text>
        </Group>
        <Button
          className={styles.manualButton}
          classNames={{ label: styles.manualButtonLabel }}
          color="blue.8"
          component={Link}
          to="/add/manual"
          variant="outline"
        >
          {t("metadata.chooseManual")}
        </Button>
      </Stack>
    );
  }
  if (providersQuery.data !== undefined && availableProviders.length === 0) {
    return (
      <Stack gap="lg">
        <Title order={1}>{t("routes.add")}</Title>
        <Text className={styles.feedback} role="alert">
          {t("metadata.providersUnavailable")}
        </Text>
        <Button
          className={styles.manualButton}
          classNames={{ label: styles.manualButtonLabel }}
          color="blue.8"
          component={Link}
          to="/add/manual"
          variant="outline"
        >
          {t("metadata.chooseManual")}
        </Button>
      </Stack>
    );
  }
  if (savedItem !== null) {
    return (
      <Stack>
        <Title order={1}>{t("metadata.saved")}</Title>
        <Group>
          <Button
            component={Link}
            to={`/items/${encodeURIComponent(savedItem.id)}`}
            variant="light"
          >
            {t("metadata.viewItem")}
          </Button>
          <Button
            component={Link}
            to={`/items/${encodeURIComponent(savedItem.id)}/releases`}
          >
            {t("routes.releases")}
          </Button>
        </Group>
      </Stack>
    );
  }

  return (
    <Stack gap="lg">
      <Title order={1}>{t("routes.add")}</Title>
      <form onSubmit={submitSearch}>
        <Group align="end">
          <TextInput
            label={t("metadata.title")}
            onChange={(event) => setQuery(event.currentTarget.value)}
            ref={searchInput}
            role="searchbox"
            value={query}
          />
          <Button
            disabled={searchMutation.isPending || selectionMutation.isPending}
            loading={searchMutation.isPending}
            type="submit"
          >
            {t("metadata.search")}
          </Button>
        </Group>
      </form>
      {searchOutcome === "pending" && (
        <Text className={styles.feedback} role="status">
          {t("search.pending", { query: submittedQuery })}
        </Text>
      )}
      {searchOutcome === "success" && (
        <Text className={styles.feedback} role="status">
          {t("search.complete", { query: submittedQuery })}
        </Text>
      )}
      {searchOutcome === "empty" && (
        <Text className={styles.feedback} role="status">
          {t("search.empty", { query: submittedQuery })}
        </Text>
      )}
      {feedbackCode !== null && (
        <Stack gap="xs">
          <Text className={styles.feedback} role="alert">
            {searchOutcome === "error" && (
              <>{t("search.failed", { query: submittedQuery })}: </>
            )}
            {t(`errors.${feedbackCode}`, {
              defaultValue: t("errors.unexpected_response"),
            })}
          </Text>
          {searchOutcome === "error" && (
            <Button
              color="blue.8"
              disabled={searchMutation.isPending}
              loading={searchMutation.isPending}
              onClick={retrySearch}
              ref={searchRetryButton}
            >
              {t("recovery.retry")}
            </Button>
          )}
        </Stack>
      )}
      {providerKeys.map((providerKey) => (
        <Fieldset key={providerKey} legend={providerKey} role="group">
          <Stack>
            {results
              .filter((result) => result.provider_key === providerKey)
              .map((result) => (
                <ResultRow
                  disabled={selectionMutation.isPending}
                  feedbackCode={
                    selectionFeedback?.token === result.token
                      ? selectionFeedback.code
                      : null
                  }
                  key={result.token}
                  onSelect={() => selectResult(result.token)}
                  pending={
                    selectionMutation.isPending &&
                    selectionMutation.variables?.token === result.token
                  }
                  result={result}
                />
              ))}
          </Stack>
        </Fieldset>
      ))}
      <Modal
        onClose={() => {
          setConfirmationOpen(false);
          setConfirmationToken(null);
        }}
        opened={confirmationOpen}
        title={t("metadata.confirmTitle")}
      >
        <Stack>
          <Text>{t("metadata.confirmDescription")}</Text>
          <Button
            disabled={confirmationToken === null || selectionMutation.isPending}
            loading={selectionMutation.isPending}
            onClick={() => {
              if (confirmationToken !== null) {
                selectResult(confirmationToken, true);
              }
            }}
          >
            {t("metadata.confirm")}
          </Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
