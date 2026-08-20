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
import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router";

import type { components } from "../api/control.generated";
import { ControlFailure } from "../api/control-client";
import { useControl } from "../api/control-provider";
import { createAcquisitionAttempt } from "./acquisition-attempt";

type ReleaseResult = components["schemas"]["ReleaseSearchResult"];
type Acquisition = components["schemas"]["AcquisitionView"];

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
  const searchMutation = useMutation({
    mutationFn: (selectedIndexerIds: number[]) =>
      client.searchReleases(itemId, query.trim(), selectedIndexerIds),
    onSuccess: (values) => {
      setResults(values);
      setReleaseToken(null);
      setDestination("");
      setFeedbackCode(null);
      setAcquisition(null);
      setIndexerIdsInvalid(false);
    },
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
  });

  useEffect(() => {
    if (destinationsQuery.isError) setDestination("");
  }, [destinationsQuery.isError]);

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    const selectedIndexerIds = parseIndexerIds(indexerIds);
    if (selectedIndexerIds === null) {
      setIndexerIdsInvalid(true);
      return;
    }
    setIndexerIdsInvalid(false);
    if (query.trim().length > 0) searchMutation.mutate(selectedIndexerIds);
  };
  const confirm = async () => {
    if (releaseToken === null || destination.length === 0) return;
    const liveDestinations = await destinationsQuery.refetch();
    if (!liveDestinations.data?.some((value) => value.key === destination)) {
      setFeedbackCode("download_destination_unavailable");
      setDestination("");
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
          <Button loading={searchMutation.isPending} type="submit">
            {t("release.search")}
          </Button>
        </Group>
      </form>
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
            onChange={(event) => setDestination(event.currentTarget.value)}
            value={destination}
          />
        )}
      <Button
        disabled={
          releaseToken === null ||
          destination.length === 0 ||
          destinationsQuery.isError
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
