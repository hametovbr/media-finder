import {
  Button,
  Fieldset,
  Group,
  Loader,
  Modal,
  Radio,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { components } from "../api/control.generated";
import { ControlFailure } from "../api/control-client";
import { useControl } from "../api/control-provider";

type SearchResult = components["schemas"]["MetadataSearchResult"];
type MediaItem = components["schemas"]["MediaItemDetail"];

export function MetadataPage() {
  const { client, session } = useControl();
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedToken, setSelectedToken] = useState<string | null>(null);
  const [savedItem, setSavedItem] = useState<MediaItem | null>(null);
  const [feedbackCode, setFeedbackCode] = useState<string | null>(null);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const providersQuery = useQuery({
    queryKey: ["control", "metadata-providers", session.ui_locale],
    queryFn: ({ signal }) => client.listMetadataProviders(signal),
  });
  const searchMutation = useMutation({
    mutationFn: () =>
      client.searchMetadata(query.trim(), session.metadata_locale),
    onSuccess: (values) => {
      setResults(values);
      setSelectedToken(null);
      setFeedbackCode(null);
      setSavedItem(null);
    },
  });
  const selectionMutation = useMutation({
    mutationFn: (confirmSimilarity: boolean) => {
      if (selectedToken === null) throw new Error("metadata_selection_missing");
      return client.selectMetadata(selectedToken, confirmSimilarity);
    },
    onSuccess: async (item) => {
      setConfirmationOpen(false);
      setSavedItem(item);
      setFeedbackCode(null);
      setSelectedToken(null);
      await queryClient.invalidateQueries({ queryKey: ["control", "catalog"] });
    },
    onError: (error) => {
      if (
        error instanceof ControlFailure &&
        error.code === "confirmation_required"
      ) {
        setConfirmationOpen(true);
        return;
      }
      const code =
        error instanceof ControlFailure ? error.code : "unexpected_response";
      setFeedbackCode(code);
      if (code === "selection_expired") {
        setResults([]);
        setSelectedToken(null);
        setConfirmationOpen(false);
      }
    },
  });

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim().length > 0) searchMutation.mutate();
  };
  const providerKeys = Array.from(
    new Set(results.map((result) => result.provider_key)),
  );

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
          <Radio.Group onChange={setSelectedToken} value={selectedToken}>
            <Stack>
              {results
                .filter((result) => result.provider_key === providerKey)
                .map((result) => (
                  <Radio
                    key={result.token}
                    label={`${providerKey} — ${result.title}${result.year ? ` (${result.year})` : ""}`}
                    value={result.token}
                  />
                ))}
            </Stack>
          </Radio.Group>
        </Fieldset>
      ))}
      {results.length > 0 && (
        <Button
          disabled={selectedToken === null}
          loading={selectionMutation.isPending}
          onClick={() => selectionMutation.mutate(false)}
        >
          {t("metadata.save")}
        </Button>
      )}
      <Modal
        onClose={() => setConfirmationOpen(false)}
        opened={confirmationOpen}
        title={t("metadata.confirmTitle")}
      >
        <Stack>
          <Text>{t("metadata.confirmDescription")}</Text>
          <Button onClick={() => selectionMutation.mutate(true)}>
            {t("metadata.confirm")}
          </Button>
        </Stack>
      </Modal>
    </Stack>
  );
}
