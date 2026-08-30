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
import { type FormEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { components } from "../api/control.generated";
import { ControlFailure } from "../api/control-client";
import { useControl } from "../api/control-provider";
import styles from "./metadata-page.module.css";

type SearchResult = components["schemas"]["MetadataSearchResult"];
type MediaItem = components["schemas"]["MediaItemDetail"];

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
          <Title order={3} size="h4">
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
  const providersQuery = useQuery({
    enabled: mode === "provider",
    queryKey: ["control", "metadata-providers", session.ui_locale],
    queryFn: ({ signal }) => client.listMetadataProviders(signal),
  });
  const searchMutation = useMutation({
    mutationFn: () =>
      client.searchMetadata(query.trim(), session.metadata_locale),
    onSuccess: (values) => {
      setResults(values);
      setFeedbackCode(null);
      setSelectionFeedback(null);
      setSavedItem(null);
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
    if (selectionInFlight.current) return;
    selectionInFlight.current = true;
    setSelectionFeedback(null);
    selectionMutation.mutate({ confirmSimilarity, token });
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim().length > 0) searchMutation.mutate();
  };
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
          <Button component={Link} to="/add/manual" variant="light">
            {t("metadata.chooseManual")}
          </Button>
        </Group>
      </Stack>
    );
  }

  if (providersQuery.isPending)
    return <Loader aria-label={t("metadata.loadingProviders")} />;
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
            role="searchbox"
            value={query}
          />
          <Button loading={searchMutation.isPending} type="submit">
            {t("metadata.search")}
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
