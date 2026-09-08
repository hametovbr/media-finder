import {
  Badge,
  Button,
  Group,
  NativeSelect,
  Radio,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";

import type { components } from "../api/control.generated";
import { ControlFailure } from "../api/control-client";
import { useControl } from "../api/control-provider";
import { createAcquisitionAttempt } from "./acquisition-attempt";

type ReleaseResult = components["schemas"]["ReleaseSearchResult"];
type Acquisition = components["schemas"]["AcquisitionView"];
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

function parseIndexerIds(value: string): number[] | null {
  if (value.trim().length === 0) return [];
  const parts = value.split(",").map((part) => part.trim());
  if (parts.some((part) => !/^\d+$/.test(part))) return null;
  const values = parts.map(Number);
  return values.every(Number.isSafeInteger) ? values : null;
}

export function ReleasePage() {
  const { client } = useControl();
  const { t } = useTranslation();
  const { itemId = "" } = useParams();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [indexerIds, setIndexerIds] = useState("");
  const [indexerIdsInvalid, setIndexerIdsInvalid] = useState(false);
  const [results, setResults] = useState<ReleaseResult[]>([]);
  const [releaseToken, setReleaseToken] = useState<string | null>(null);
  const [destination, setDestination] = useState("");
  const [feedbackCode, setFeedbackCode] = useState<string | null>(null);
  const [acquisition, setAcquisition] = useState<Acquisition | null>(null);
  const [searchOutcome, setSearchOutcome] = useState<SearchOutcome>({
    kind: "initial",
  });
  const [retryRequest, setRetryRequest] = useState<ReleaseSearchRequest | null>(
    null,
  );
  const [acquisitionStarting, setAcquisitionStarting] = useState(false);
  const [restoreSearchFocus, setRestoreSearchFocus] = useState(false);
  const mounted = useRef(true);
  const activeSearch = useRef<ReleaseSearchRequest | null>(null);
  const searchButton = useRef<HTMLButtonElement>(null);
  const retryButton = useRef<HTMLButtonElement>(null);
  const searchInFlight = useRef(false);
  const acquisitionInFlight = useRef(false);
  const searchPending = searchOutcome.kind === "pending";
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
      setAcquisition(null);
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
      setAcquisition(null);
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
    mutationFn: (attempt: () => Promise<Acquisition>) => attempt(),
    retry: (count, error) =>
      count < 1 && error instanceof ControlFailure && error.status >= 500,
    onSuccess: async (value) => {
      setAcquisition(value);
      setFeedbackCode(null);
      await queryClient.invalidateQueries({ queryKey: ["control", "catalog"] });
    },
    onError: (error) => {
      const code =
        error instanceof ControlFailure ? error.code : "unexpected_response";
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
    },
    onSettled: () => {
      acquisitionInFlight.current = false;
      setAcquisitionStarting(false);
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
    activeSearch.current = null;
    searchInFlight.current = false;
    setResults([]);
    setReleaseToken(null);
    setDestination("");
    setSearchOutcome({ kind: "initial" });
    setRetryRequest(null);
  }, [itemId]);

  useEffect(() => {
    if (!restoreSearchFocus) return;
    searchButton.current?.focus();
    setRestoreSearchFocus(false);
  }, [restoreSearchFocus]);

  const startSearch = (request: ReleaseSearchRequest) => {
    if (searchInFlight.current || acquisitionInFlight.current) return;
    searchInFlight.current = true;
    activeSearch.current = request;
    setResults([]);
    setReleaseToken(null);
    setDestination("");
    setSearchOutcome({ kind: "pending", request });
    if (retryRequest !== request) setRetryRequest(null);
    searchMutation.mutate(request);
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    const selectedIndexerIds = parseIndexerIds(indexerIds);
    if (selectedIndexerIds === null) {
      setIndexerIdsInvalid(true);
      return;
    }
    setIndexerIdsInvalid(false);
    const submittedQuery = query.trim();
    if (submittedQuery.length > 0) {
      startSearch({
        indexerIds: selectedIndexerIds,
        itemId,
        query: submittedQuery,
      });
    }
  };
  const confirm = async () => {
    if (
      acquisitionInFlight.current ||
      releaseToken === null ||
      destination.length === 0
    )
      return;
    acquisitionInFlight.current = true;
    setAcquisitionStarting(true);
    const liveDestinations = await destinationsQuery.refetch();
    if (!liveDestinations.data?.some((value) => value.key === destination)) {
      setFeedbackCode("download_destination_unavailable");
      setDestination("");
      acquisitionInFlight.current = false;
      setAcquisitionStarting(false);
      return;
    }
    submissionMutation.mutate(
      createAcquisitionAttempt((request) => client.submitAcquisition(request), {
        destination,
        mediaItemId: itemId,
        releaseToken,
      }),
    );
  };

  return (
    <Stack gap="lg">
      <Title order={1}>{t("routes.releases")}</Title>
      <form onSubmit={submitSearch}>
        <Group align="end">
          <TextInput
            label={t("release.query")}
            onChange={(event) => setQuery(event.currentTarget.value)}
            role="searchbox"
            value={query}
          />
          <TextInput
            description={t("release.indexerIdsDescription")}
            error={
              indexerIdsInvalid ? t("errors.release_filter_invalid") : undefined
            }
            label={t("release.indexerIds")}
            onChange={(event) => {
              setIndexerIds(event.currentTarget.value);
              setIndexerIdsInvalid(false);
            }}
            value={indexerIds}
          />
          <Button
            disabled={
              searchPending ||
              submissionMutation.isPending ||
              acquisitionStarting
            }
            loading={searchPending}
            ref={searchButton}
            type="submit"
          >
            {t("release.search")}
          </Button>
        </Group>
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
            disabled={
              searchPending ||
              acquisitionStarting ||
              submissionMutation.isPending
            }
            onClick={() => startSearch(retryRequest)}
            ref={retryButton}
            variant="light"
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
        <Text role="alert">
          {t(
            `errors.${
              destinationsQuery.error instanceof ControlFailure
                ? destinationsQuery.error.code
                : "unexpected_response"
            }`,
            { defaultValue: t("errors.unexpected_response") },
          )}
        </Text>
      )}
      {results.length > 0 && (
        <Radio.Group
          disabled={
            searchPending || submissionMutation.isPending || acquisitionStarting
          }
          label={t("release.results")}
          onChange={(value) => {
            setReleaseToken(value);
            setDestination("");
          }}
          value={releaseToken}
        >
          <Stack>
            {results.map((result) => (
              <Radio
                key={result.token}
                label={`${result.title}${result.seeders == null ? "" : ` — ${result.seeders} ${t("release.seeders")}`}`}
                value={result.token}
              />
            ))}
          </Stack>
        </Radio.Group>
      )}
      {releaseToken !== null &&
        !destinationsQuery.isError &&
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
              searchPending ||
              submissionMutation.isPending ||
              acquisitionStarting
            }
            onChange={(event) => setDestination(event.currentTarget.value)}
            value={destination}
          />
        )}
      <Button
        disabled={
          releaseToken === null ||
          destination.length === 0 ||
          destinationsQuery.isError ||
          searchPending ||
          acquisitionStarting
        }
        loading={submissionMutation.isPending}
        onClick={() => void confirm()}
      >
        {t("release.confirm")}
      </Button>
      {acquisition !== null && (
        <Stack aria-live="polite">
          <Badge
            color={
              acquisition.status === "failed"
                ? "red"
                : acquisition.status === "pending"
                  ? "yellow"
                  : "green"
            }
          >
            {acquisition.status === "pending"
              ? t("catalog.pendingReconciliation")
              : t(`acquisition.${acquisition.status}`)}
          </Badge>
          {acquisition.error_code != null && (
            <Text>
              {t(`errors.${acquisition.error_code}`, {
                defaultValue: t("errors.unexpected_response"),
              })}
            </Text>
          )}
        </Stack>
      )}
    </Stack>
  );
}
