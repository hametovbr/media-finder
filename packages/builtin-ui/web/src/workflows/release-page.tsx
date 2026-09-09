import {
  Badge,
  Button,
  Collapse,
  Group,
  Modal,
  NativeSelect,
  Radio,
  Stack,
  Text,
  TextInput,
  Title,
  UnstyledButton,
  VisuallyHidden,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router";

import type { components } from "../api/control.generated";
import { ControlFailure } from "../api/control-client";
import { useControl } from "../api/control-provider";
import { createAcquisitionAttempt } from "./acquisition-attempt";

type ReleaseResult = components["schemas"]["ReleaseSearchResult"];
type Acquisition = components["schemas"]["AcquisitionView"];
type MediaItemDetail = components["schemas"]["MediaItemDetail"];
type ReleaseSearchRequest = {
  indexerIds: number[];
  itemId: string;
  query: string;
};
type SearchOutcome =
  | { kind: "initial" }
  | { kind: "pending"; request: ReleaseSearchRequest }
  | { kind: "complete"; request: ReleaseSearchRequest }
  | { kind: "empty"; request: ReleaseSearchRequest }
  | { code: string; kind: "failed"; request: ReleaseSearchRequest };

type SubmissionPhase = "idle" | "preflight" | "submitting" | "uncertain";
type ReviewIntent = {
  destination: string;
  destinationLabel: string;
  releaseTitle: string;
  workTitle: string;
};
type RetainedAttempt = ReviewIntent & {
  itemId: string;
  run: () => Promise<Acquisition>;
};
type AcquisitionOutcome = {
  acquisition: Acquisition;
  destinationLabel: string;
  releaseTitle: string;
  workTitle: string;
};

const RELEASE_QUERY_MAX_LENGTH = 500;
const binaryUnitKeys = ["bytes", "kib", "mib", "gib", "tib", "pib"] as const;
const definitiveSubmissionFailureStatuses: Readonly<Record<string, number>> = {
  csrf_invalid: 403,
  download_destination_unavailable: 409,
  json_required: 415,
  media_item_not_found: 404,
  method_not_allowed: 405,
  not_found: 404,
  origin_invalid: 403,
  release_search_token_expired: 410,
  release_selection_invalid: 422,
  request_body_invalid: 400,
  request_body_too_large: 413,
  request_invalid: 422,
  selection_expired: 410,
  session_invalid: 403,
};

function formatBinarySize(
  size: number | null | undefined,
  locale: string,
  unit: (key: string) => string,
): string | null {
  if (size === null || size === undefined) return null;
  let value = size;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < binaryUnitKeys.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const formatted = new Intl.NumberFormat(locale, {
    maximumFractionDigits: unitIndex === 0 ? 0 : 2,
  }).format(value);
  return `${formatted} ${unit(`release.units.${binaryUnitKeys[unitIndex]}`)}`;
}

function parseIndexerIds(value: string): number[] | null {
  if (value.trim().length === 0) return [];
  const parts = value.split(",").map((part) => part.trim());
  if (parts.some((part) => !/^\d+$/.test(part))) return null;
  const values = parts.map(Number);
  return values.every(Number.isSafeInteger) ? values : null;
}

function isKnownDefinitiveSubmissionFailure(failure: ControlFailure): boolean {
  return (
    definitiveSubmissionFailureStatuses[failure.code] === failure.status ||
    // The release-token bounds check can also surface this legacy code as 422.
    (failure.code === "release_search_token_expired" && failure.status === 422)
  );
}

function contextTitle(
  item: MediaItemDetail,
  locale: components["schemas"]["Locale"],
): string {
  const candidates = [
    item.metadata.titles[locale],
    item.metadata.titles.en,
    item.metadata.original_title,
    item.external_id,
  ];
  return candidates.find(
    (value): value is string =>
      typeof value === "string" && value.trim().length > 0,
  )!;
}

export function ReleasePage() {
  const { itemId = "" } = useParams();
  return <ReleasePageWorkflow itemId={itemId} key={itemId} />;
}

function ReleasePageWorkflow({ itemId }: { itemId: string }) {
  const { client, session } = useControl();
  const { i18n, t } = useTranslation();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [queryInvalid, setQueryInvalid] = useState(false);
  const [indexerIds, setIndexerIds] = useState("");
  const [indexerIdsInvalid, setIndexerIdsInvalid] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [results, setResults] = useState<ReleaseResult[]>([]);
  const [releaseToken, setReleaseToken] = useState<string | null>(null);
  const [destination, setDestination] = useState("");
  const [feedbackCode, setFeedbackCode] = useState<string | null>(null);
  const [review, setReview] = useState<ReviewIntent | null>(null);
  const [uncertainAttempt, setUncertainAttempt] =
    useState<RetainedAttempt | null>(null);
  const [acquisitionOutcome, setAcquisitionOutcome] =
    useState<AcquisitionOutcome | null>(null);
  const [submissionPhase, setSubmissionPhase] =
    useState<SubmissionPhase>("idle");
  const [searchOutcome, setSearchOutcome] = useState<SearchOutcome>({
    kind: "initial",
  });
  const [retryRequest, setRetryRequest] = useState<ReleaseSearchRequest | null>(
    null,
  );
  const [restoreSearchFocus, setRestoreSearchFocus] = useState(false);
  const mounted = useRef(true);
  const activeSearch = useRef<ReleaseSearchRequest | null>(null);
  const searchButton = useRef<HTMLButtonElement>(null);
  const reviewTrigger = useRef<HTMLButtonElement>(null);
  const retryButton = useRef<HTMLButtonElement>(null);
  const indexerInput = useRef<HTMLInputElement>(null);
  const searchInFlight = useRef(false);
  const acquisitionInFlight = useRef(false);
  const queryEdited = useRef(false);
  const prefillDone = useRef(false);
  const lastContextItemId = useRef<string | null>(null);
  const reviewWasOpen = useRef(false);
  const searchPending = searchOutcome.kind === "pending";
  const workflowLocked = review !== null || submissionPhase !== "idle";
  const selectionLocked = workflowLocked || acquisitionOutcome !== null;
  const contextQuery = useQuery({
    queryKey: ["control", "media-item", itemId, session.metadata_locale],
    queryFn: ({ signal }) =>
      client.getMediaItem(itemId, session.metadata_locale, signal),
    enabled: itemId.length > 0,
    retry: false,
  });
  const contextReady = contextQuery.data !== undefined && !contextQuery.isError;
  const searchMutation = useMutation({
    mutationFn: (request: ReleaseSearchRequest) =>
      client.searchReleases(request.itemId, request.query, request.indexerIds),
    onError: (error, request) => {
      if (!mounted.current || activeSearch.current !== request) return;
      setSearchOutcome({
        code:
          error instanceof ControlFailure ? error.code : "unexpected_response",
        kind: "failed",
        request,
      });
      setRetryRequest(request);
      setAcquisitionOutcome(null);
      setFeedbackCode(null);
    },
    onSuccess: (values, request) => {
      if (!mounted.current || activeSearch.current !== request) return;
      if (document.activeElement === retryButton.current) {
        setRestoreSearchFocus(true);
      }
      setResults(values);
      setSearchOutcome({
        kind: values.length === 0 ? "empty" : "complete",
        request,
      });
      setAcquisitionOutcome(null);
      setFeedbackCode(null);
      setIndexerIdsInvalid(false);
      setRetryRequest(null);
    },
    onSettled: (_data, _error, request) => {
      if (activeSearch.current === request) {
        searchInFlight.current = false;
      }
    },
    retry: false,
  });
  const destinationsQuery = useQuery({
    queryKey: ["control", "download-destinations", releaseToken],
    queryFn: ({ signal }) => client.listDownloadDestinations(signal),
    enabled: releaseToken !== null,
    staleTime: 0,
  });
  const submissionMutation = useMutation({
    mutationFn: (attempt: RetainedAttempt) => attempt.run(),
    retry: false,
    onSuccess: (value, attempt) => {
      // This invalidation deliberately runs even when the originating page has
      // been abandoned; React Query may drop local mutate callbacks on unmount.
      const invalidation = Promise.all([
        queryClient.invalidateQueries({ queryKey: ["control", "catalog"] }),
        queryClient.invalidateQueries({
          queryKey: ["control", "media-item", attempt.itemId],
        }),
      ]);
      if (!mounted.current) {
        void invalidation.catch(() => undefined);
        return;
      }
      acquisitionInFlight.current = false;
      setAcquisitionOutcome({
        acquisition: value,
        destinationLabel: attempt.destinationLabel,
        releaseTitle: attempt.releaseTitle,
        workTitle: attempt.workTitle,
      });
      setFeedbackCode(null);
      setUncertainAttempt(null);
      setReview(null);
      setSubmissionPhase("idle");
      setResults([]);
      setReleaseToken(null);
      setDestination("");
      void invalidation.catch(() => undefined);
    },
  });

  useEffect(() => {
    if (destinationsQuery.isError) setDestination("");
  }, [destinationsQuery.isError]);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (contextQuery.data === undefined) return;
    if (lastContextItemId.current === contextQuery.data.id) return;
    lastContextItemId.current = contextQuery.data.id;
    if (prefillDone.current || queryEdited.current) {
      prefillDone.current = true;
      return;
    }
    setQuery(contextTitle(contextQuery.data, session.metadata_locale));
    prefillDone.current = true;
  }, [contextQuery.data, session.metadata_locale]);

  useEffect(() => {
    if (indexerIdsInvalid && advancedOpen) indexerInput.current?.focus();
  }, [advancedOpen, indexerIdsInvalid]);

  useEffect(() => {
    if (!restoreSearchFocus) return;
    searchButton.current?.focus();
    setRestoreSearchFocus(false);
  }, [restoreSearchFocus]);

  useEffect(() => {
    if (review !== null) {
      reviewWasOpen.current = true;
      return;
    }
    if (reviewWasOpen.current && submissionPhase === "idle") {
      reviewWasOpen.current = false;
      reviewTrigger.current?.focus();
    }
  }, [review, submissionPhase]);

  const startSearch = (request: ReleaseSearchRequest) => {
    if (
      !contextReady ||
      searchInFlight.current ||
      acquisitionInFlight.current ||
      uncertainAttempt !== null ||
      review !== null ||
      submissionPhase !== "idle"
    )
      return;
    searchInFlight.current = true;
    activeSearch.current = request;
    setResults([]);
    setReleaseToken(null);
    setDestination("");
    setAcquisitionOutcome(null);
    setFeedbackCode(null);
    setSearchOutcome({ kind: "pending", request });
    if (retryRequest !== request) setRetryRequest(null);
    searchMutation.mutate(request);
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    if (!contextReady) return;
    const selectedIndexerIds = parseIndexerIds(indexerIds);
    if (selectedIndexerIds === null) {
      setIndexerIdsInvalid(true);
      setAdvancedOpen(true);
      return;
    }
    setIndexerIdsInvalid(false);
    const submittedQuery = query.trim();
    if (query.length > RELEASE_QUERY_MAX_LENGTH) {
      setQueryInvalid(true);
      return;
    }
    setQueryInvalid(false);
    if (submittedQuery.length > 0) {
      startSearch({
        indexerIds: selectedIndexerIds,
        itemId,
        query: submittedQuery,
      });
    }
  };
  const finishDefinitiveFailure = (code: string) => {
    acquisitionInFlight.current = false;
    setSubmissionPhase("idle");
    setUncertainAttempt(null);
    setReview(null);
    setFeedbackCode(code);
    if (
      code === "release_search_token_expired" ||
      code === "release_selection_invalid" ||
      code === "selection_expired"
    ) {
      setResults([]);
      setReleaseToken(null);
      setDestination("");
    }
  };

  const refreshDestinations = (
    message: string | null,
    admissionAlreadyHeld = false,
  ) => {
    if (
      !mounted.current ||
      (!admissionAlreadyHeld && acquisitionInFlight.current)
    )
      return;
    if (!admissionAlreadyHeld) acquisitionInFlight.current = true;
    setSubmissionPhase("preflight");
    setFeedbackCode(message);
    void (async () => {
      let reload;
      try {
        reload = await destinationsQuery.refetch();
      } catch {
        reload = null;
      }
      if (!mounted.current) return;
      acquisitionInFlight.current = false;
      setSubmissionPhase("idle");
      if (reload === null || reload.isError || reload.data === undefined) {
        setFeedbackCode(null);
      }
    })();
  };

  const handleSubmissionError = async (
    error: unknown,
    attempt: RetainedAttempt,
  ) => {
    if (!mounted.current) return;
    const failure = error instanceof ControlFailure ? error : null;
    const code = failure?.code ?? "unexpected_response";
    if (
      failure !== null &&
      code === "download_destination_unavailable" &&
      isKnownDefinitiveSubmissionFailure(failure)
    ) {
      // This domain rejection occurs before token consumption. Discard this
      // intent and explicitly reload destinations; keep the release token.
      setUncertainAttempt(null);
      setReview(null);
      setDestination("");
      refreshDestinations(code, true);
      return;
    }
    if (
      failure !== null &&
      (code === "release_search_token_expired" ||
        code === "release_selection_invalid" ||
        code === "selection_expired") &&
      isKnownDefinitiveSubmissionFailure(failure)
    ) {
      finishDefinitiveFailure(code);
      return;
    }
    if (failure !== null && isKnownDefinitiveSubmissionFailure(failure)) {
      finishDefinitiveFailure(code);
      return;
    }
    // A transport, 5xx, or unknown exception leaves acceptance uncertain. The
    // only available action is an explicit retry of this exact retained run.
    acquisitionInFlight.current = false;
    setSubmissionPhase("uncertain");
    setUncertainAttempt(attempt);
    setFeedbackCode(null);
  };

  const runAttempt = async (
    attempt: RetainedAttempt,
    preflight: boolean,
  ): Promise<void> => {
    if (!mounted.current) return;
    if (preflight) {
      setSubmissionPhase("preflight");
      let liveDestinations;
      try {
        liveDestinations = await destinationsQuery.refetch();
      } catch (error) {
        if (!mounted.current) return;
        finishDefinitiveFailure(
          error instanceof ControlFailure
            ? error.code
            : "download_client_unavailable",
        );
        setDestination("");
        return;
      }
      // The route key/unmount check must happen after the await and before any
      // mutation admission. An abandoned preflight therefore sends zero POSTs.
      if (!mounted.current) return;
      if (liveDestinations.isError || liveDestinations.data === undefined) {
        finishDefinitiveFailure(
          liveDestinations.error instanceof ControlFailure
            ? liveDestinations.error.code
            : "download_client_unavailable",
        );
        setFeedbackCode(null);
        setDestination("");
        return;
      }
      if (
        !liveDestinations.data.some(
          (value) => value.key === attempt.destination,
        )
      ) {
        finishDefinitiveFailure("download_destination_unavailable");
        setDestination("");
        return;
      }
    }
    if (!mounted.current) return;
    setSubmissionPhase("submitting");
    try {
      await submissionMutation.mutateAsync(attempt);
    } catch (error) {
      await handleSubmissionError(error, attempt);
    }
  };

  const openReview = () => {
    if (
      !contextReady ||
      selectionLocked ||
      releaseToken === null ||
      destination.length === 0 ||
      destinationsQuery.data === undefined
    )
      return;
    const result = results.find((value) => value.token === releaseToken);
    if (!result) return;
    const selectedDestination = destinationsQuery.data.find(
      (value) => value.key === destination,
    );
    if (!selectedDestination) return;
    setFeedbackCode(null);
    setReview({
      destination,
      destinationLabel: selectedDestination.label,
      releaseTitle: result.title,
      workTitle: contextTitle(contextQuery.data!, session.metadata_locale),
    });
  };

  const confirmReview = () => {
    if (
      review === null ||
      acquisitionInFlight.current ||
      releaseToken === null ||
      !contextReady
    )
      return;
    // Set the synchronous guard before any state update or await. Repeated
    // clicks cannot allocate another UUID or preflight.
    acquisitionInFlight.current = true;
    const attempt: RetainedAttempt = {
      ...review,
      itemId,
      run: createAcquisitionAttempt(
        (request) => client.submitAcquisition(request),
        {
          destination: review.destination,
          mediaItemId: itemId,
          releaseToken,
        },
      ),
    };
    setReview(null);
    void runAttempt(attempt, true);
  };

  const retryUncertain = () => {
    if (
      uncertainAttempt === null ||
      !mounted.current ||
      submissionPhase !== "uncertain" ||
      acquisitionInFlight.current
    )
      return;
    acquisitionInFlight.current = true;
    setFeedbackCode(null);
    void runAttempt(uncertainAttempt, false);
  };

  return (
    <>
      <Stack gap="lg">
        <Group align="center" justify="space-between" wrap="wrap">
          <Title order={1}>{t("routes.releases")}</Title>
          <Button
            component={Link}
            to={`/items/${encodeURIComponent(itemId)}`}
            variant="subtle"
          >
            {t("release.backToItem")}
          </Button>
        </Group>
        {contextQuery.isPending && (
          <Text aria-live="polite" role="status">
            {t("release.contextLoading")}
          </Text>
        )}
        {contextQuery.data !== undefined && (
          <Group gap="xs" wrap="wrap">
            <Text c="dimmed" fw={600}>
              {t("release.contextLabel")}
            </Text>
            <Text style={{ overflowWrap: "anywhere" }}>
              {contextTitle(contextQuery.data, session.metadata_locale)}
            </Text>
          </Group>
        )}
        {contextQuery.isError && (
          <Stack gap="xs" role="alert">
            <Text>{t("release.contextFailed")}</Text>
            <Text>
              {t(
                `errors.${
                  contextQuery.error instanceof ControlFailure
                    ? contextQuery.error.code
                    : "unexpected_response"
                }`,
                { defaultValue: t("errors.unexpected_response") },
              )}
            </Text>
            <Button
              aria-label={t("release.retryContext")}
              color="blue.8"
              disabled={contextQuery.isFetching}
              loading={contextQuery.isFetching}
              onClick={() => void contextQuery.refetch()}
            >
              {t("recovery.retry")}
            </Button>
          </Stack>
        )}
        <form onSubmit={submitSearch}>
          <Stack gap="sm">
            <Group align="end" wrap="wrap">
              <TextInput
                disabled={workflowLocked}
                error={queryInvalid ? t("release.queryTooLong") : undefined}
                label={t("release.query")}
                onChange={(event) => {
                  queryEdited.current = true;
                  setQuery(event.currentTarget.value);
                  setQueryInvalid(false);
                }}
                role="searchbox"
                value={query}
              />
              <Button
                disabled={!contextReady || searchPending || workflowLocked}
                loading={searchPending}
                ref={searchButton}
                type="submit"
              >
                {t("release.search")}
              </Button>
            </Group>
            <UnstyledButton
              aria-controls={`release-advanced-${itemId}`}
              aria-expanded={advancedOpen}
              disabled={workflowLocked}
              onClick={() => setAdvancedOpen((open) => !open)}
              style={{
                height: "auto",
                minHeight: "2.25rem",
                overflowWrap: "anywhere",
                textAlign: "start",
                whiteSpace: "normal",
              }}
              type="button"
            >
              {t("release.advancedFilters")}
            </UnstyledButton>
            <Collapse
              expanded={advancedOpen}
              id={`release-advanced-${itemId}`}
              keepMounted
              keepMountedMode="display-none"
              transitionDuration={0}
            >
              <TextInput
                disabled={workflowLocked}
                ref={indexerInput}
                description={t("release.indexerIdsDescription")}
                error={
                  indexerIdsInvalid
                    ? t("errors.release_filter_invalid")
                    : undefined
                }
                label={t("release.indexerIds")}
                onChange={(event) => {
                  setIndexerIds(event.currentTarget.value);
                  setIndexerIdsInvalid(false);
                }}
                value={indexerIds}
              />
            </Collapse>
          </Stack>
        </form>
        {searchOutcome.kind === "pending" && (
          <Text
            aria-live="polite"
            role="status"
            style={{ overflowWrap: "anywhere" }}
          >
            {t("search.pending", { query: searchOutcome.request.query })}
          </Text>
        )}
        {searchOutcome.kind === "complete" && (
          <Text
            aria-live="polite"
            role="status"
            style={{ overflowWrap: "anywhere" }}
          >
            {t("search.complete", { query: searchOutcome.request.query })}
          </Text>
        )}
        {searchOutcome.kind === "empty" && (
          <Text
            aria-live="polite"
            role="status"
            style={{ overflowWrap: "anywhere" }}
          >
            {t("search.empty", { query: searchOutcome.request.query })}
          </Text>
        )}
        {searchOutcome.kind === "failed" && (
          <Stack gap="xs" role="alert">
            <Text style={{ overflowWrap: "anywhere" }}>
              {t("search.failed", { query: searchOutcome.request.query })}
            </Text>
            <Text>
              {t(`errors.${searchOutcome.code}`, {
                defaultValue: t("errors.unexpected_response"),
              })}
            </Text>
          </Stack>
        )}
        {retryRequest !== null &&
          (searchOutcome.kind === "failed" ||
            searchOutcome.kind === "pending") && (
            <Button
              color="blue.8"
              disabled={!contextReady || searchPending || workflowLocked}
              onClick={() => startSearch(retryRequest)}
              ref={retryButton}
            >
              {t("recovery.retry")}
            </Button>
          )}
        {feedbackCode !== null && (
          <Text role="alert">
            {t(`errors.${feedbackCode}`, {
              defaultValue: t("errors.unexpected_response"),
            })}
          </Text>
        )}
        {destinationsQuery.isError && (
          <Stack gap="xs" role="alert">
            <Text>
              {t(
                `errors.${
                  destinationsQuery.error instanceof ControlFailure
                    ? destinationsQuery.error.code
                    : "unexpected_response"
                }`,
                { defaultValue: t("errors.unexpected_response") },
              )}
            </Text>
            <Button
              disabled={destinationsQuery.isFetching || workflowLocked}
              loading={destinationsQuery.isFetching}
              onClick={() => refreshDestinations(null)}
              style={{
                height: "auto",
                minHeight: "2.25rem",
                whiteSpace: "normal",
              }}
            >
              {t("release.retryDestinations")}
            </Button>
          </Stack>
        )}
        {results.length > 0 && (
          <Radio.Group
            disabled={searchPending || selectionLocked}
            label={t("release.results")}
            onChange={(value) => {
              setReleaseToken(value);
              setDestination("");
            }}
            value={releaseToken}
          >
            <Stack gap="md">
              {results.map((result, index) => {
                const factsId = `release-facts-${itemId}-${index}`;
                const formattedSize = formatBinarySize(
                  result.size,
                  i18n.resolvedLanguage ?? "en",
                  (key) => t(key),
                );
                return (
                  <Stack
                    gap="xs"
                    key={result.token}
                    style={{ minWidth: 0, overflowWrap: "anywhere" }}
                  >
                    <Radio
                      aria-describedby={factsId}
                      label={result.title}
                      value={result.token}
                    />
                    <Stack gap={2} id={factsId} ml="xl" style={{ minWidth: 0 }}>
                      <Text style={{ overflowWrap: "anywhere" }}>
                        <Text component="span" fw={600}>
                          {t("release.indexer")}:
                        </Text>{" "}
                        {result.indexer?.trim() || t("release.unknown")}
                      </Text>
                      <Text style={{ overflowWrap: "anywhere" }}>
                        <Text component="span" fw={600}>
                          {t("release.size")}:
                        </Text>{" "}
                        {formattedSize === null ? (
                          t("release.unknown")
                        ) : (
                          <>
                            <Text component="span">{formattedSize}</Text>
                            <VisuallyHidden>
                              {t("release.exactBytes", {
                                bytes: result.size,
                              })}
                            </VisuallyHidden>
                          </>
                        )}
                      </Text>
                      <Text style={{ overflowWrap: "anywhere" }}>
                        <Text component="span" fw={600}>
                          {t("release.seeders")}:
                        </Text>{" "}
                        {result.seeders == null
                          ? t("release.unknown")
                          : result.seeders}
                      </Text>
                    </Stack>
                  </Stack>
                );
              })}
            </Stack>
          </Radio.Group>
        )}
        {releaseToken !== null &&
          !destinationsQuery.isError &&
          !destinationsQuery.isFetching &&
          destinationsQuery.data !== undefined && (
            <NativeSelect
              data={[
                { label: t("release.chooseDestination"), value: "" },
                ...destinationsQuery.data.map((value) => ({
                  label: value.label,
                  value: value.key,
                })),
              ]}
              label={t("release.destination")}
              disabled={
                searchPending || destinationsQuery.isFetching || selectionLocked
              }
              onChange={(event) => setDestination(event.currentTarget.value)}
              value={destination}
            />
          )}
        <Button
          disabled={
            !contextReady ||
            releaseToken === null ||
            destination.length === 0 ||
            destinationsQuery.isError ||
            searchPending ||
            selectionLocked
          }
          loading={
            submissionPhase === "preflight" || submissionPhase === "submitting"
          }
          onClick={openReview}
          ref={reviewTrigger}
        >
          {t("release.confirm")}
        </Button>
        {uncertainAttempt !== null && (
          <Stack aria-live="polite" role="alert">
            <Text>{t("release.requestUncertain")}</Text>
            <Text>{t("release.localRetryWarning")}</Text>
            <Button
              disabled={submissionPhase === "submitting"}
              loading={submissionPhase === "submitting"}
              onClick={retryUncertain}
              style={{
                height: "auto",
                minHeight: "2.25rem",
                whiteSpace: "normal",
              }}
            >
              {t("release.retryRequest")}
            </Button>
          </Stack>
        )}
        {acquisitionOutcome !== null && (
          <Stack aria-live="polite" role="status">
            <Group gap="xs" wrap="wrap">
              <Badge
                color={
                  acquisitionOutcome.acquisition.status === "failed"
                    ? "red"
                    : acquisitionOutcome.acquisition.status === "pending"
                      ? "yellow"
                      : "green"
                }
              >
                {t(`acquisition.${acquisitionOutcome.acquisition.status}`)}
              </Badge>
              <Text style={{ overflowWrap: "anywhere" }}>
                {acquisitionOutcome.workTitle}
              </Text>
            </Group>
            <Text style={{ overflowWrap: "anywhere" }}>
              {t("release.outcomeRelease", {
                release: acquisitionOutcome.releaseTitle,
              })}
            </Text>
            <Text style={{ overflowWrap: "anywhere" }}>
              {t("release.outcomeDestination", {
                destination: acquisitionOutcome.destinationLabel,
              })}
            </Text>
            <Text style={{ overflowWrap: "anywhere" }}>
              {t(`release.outcome.${acquisitionOutcome.acquisition.status}`)}
            </Text>
            {acquisitionOutcome.acquisition.error_code != null && (
              <Text style={{ overflowWrap: "anywhere" }}>
                {t(`errors.${acquisitionOutcome.acquisition.error_code}`, {
                  defaultValue: t("errors.unexpected_response"),
                })}
              </Text>
            )}
          </Stack>
        )}
      </Stack>
      <Modal
        closeOnClickOutside={submissionPhase === "idle"}
        closeOnEscape={submissionPhase === "idle"}
        opened={review !== null}
        onClose={() => {
          if (submissionPhase === "idle") setReview(null);
        }}
        returnFocus
        title={t("release.reviewTitle")}
        transitionProps={{ duration: 0 }}
        withCloseButton={false}
      >
        {review !== null && (
          <Stack>
            <Text style={{ overflowWrap: "anywhere" }}>
              <Text component="span" fw={600}>
                {t("release.reviewWork")}:
              </Text>{" "}
              {review.workTitle}
            </Text>
            <Text style={{ overflowWrap: "anywhere" }}>
              <Text component="span" fw={600}>
                {t("release.reviewRelease")}:
              </Text>{" "}
              {review.releaseTitle}
            </Text>
            <Text style={{ overflowWrap: "anywhere" }}>
              <Text component="span" fw={600}>
                {t("release.reviewDestination")}:
              </Text>{" "}
              {review.destinationLabel}
            </Text>
            <Group justify="flex-end" wrap="wrap">
              <Button
                data-autofocus
                disabled={submissionPhase !== "idle"}
                onClick={() => setReview(null)}
                style={{
                  height: "auto",
                  minHeight: "2.25rem",
                  whiteSpace: "normal",
                }}
                variant="default"
              >
                {t("release.cancelReview")}
              </Button>
              <Button
                disabled={submissionPhase !== "idle"}
                loading={submissionPhase === "preflight"}
                onClick={confirmReview}
                style={{
                  height: "auto",
                  minHeight: "2.25rem",
                  whiteSpace: "normal",
                }}
              >
                {t("release.confirmReview")}
              </Button>
            </Group>
          </Stack>
        )}
      </Modal>
    </>
  );
}
