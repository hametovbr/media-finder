import {
  Button,
  FileInput,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";

import { ControlFailure } from "../api/control-client";
import type { components } from "../api/control.generated";
import { useControl } from "../api/control-provider";
import { ManualEditor } from "./manual-editor";
import {
  manualDocumentFromItem,
  type ManualEditorDocument,
  toManualDocument,
  withManualRowKeys,
} from "./manual-document";

type MediaItem = components["schemas"]["MediaItemDetail"];
type Collection = components["schemas"]["CollectionView"];
const MAX_CSV_BYTES = 1024 * 1024;

function ManualEditForm({
  collections,
  item,
}: {
  collections: Collection[];
  item: MediaItem;
}) {
  const { client, session } = useControl();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [document, setDocument] = useState<ManualEditorDocument>(() =>
    withManualRowKeys(
      manualDocumentFromItem(item, session.metadata_locale),
      () => globalThis.crypto.randomUUID(),
    ),
  );
  const [collectionId, setCollectionId] = useState<string | null>(
    item.collection_id ?? null,
  );
  const [feedbackCode, setFeedbackCode] = useState<string | null>(null);
  const [confirmationToken, setConfirmationToken] = useState<string | null>(
    null,
  );
  const [csv, setCsv] = useState("");
  const [csvFeedback, setCsvFeedback] = useState<string | null>(null);
  async function finish(updated: MediaItem) {
    setConfirmationToken(null);
    setFeedbackCode(null);
    await queryClient.invalidateQueries({ queryKey: ["control", "catalog"] });
    queryClient.setQueryData(
      ["control", "media-item", item.id, session.metadata_locale],
      updated,
    );
    void navigate(`/items/${encodeURIComponent(item.id)}`);
  }
  const mutation = useMutation({
    mutationFn: (editorDocument: ManualEditorDocument) =>
      client.editManual(item.id, toManualDocument(editorDocument)),
    onSuccess: finish,
    onError: (error) => {
      if (
        error instanceof ControlFailure &&
        error.code === "confirmation_required" &&
        error.confirmationToken !== null
      ) {
        setConfirmationToken(error.confirmationToken);
        setFeedbackCode(null);
        return;
      }
      setFeedbackCode(
        error instanceof ControlFailure ? error.code : "unexpected_response",
      );
    },
  });
  const confirmationMutation = useMutation({
    mutationFn: (token: string) => client.confirmManual(token),
    onSuccess: finish,
    onError: (error) => {
      setConfirmationToken(null);
      setFeedbackCode(
        error instanceof ControlFailure && error.code === "selection_expired"
          ? "manual_confirmation_expired"
          : error instanceof ControlFailure
            ? error.code
            : "unexpected_response",
      );
    },
  });
  const csvMutation = useMutation({
    mutationFn: (source: string) => client.importEpisodes(item.id, source),
    onSuccess: finish,
    onError: (error) =>
      setCsvFeedback(
        error instanceof ControlFailure ? error.code : "unexpected_response",
      ),
  });

  function submitCsv() {
    if (csv.length === 0) {
      setCsvFeedback("episode_csv_empty");
      return;
    }
    if (new TextEncoder().encode(csv).byteLength > MAX_CSV_BYTES) {
      setCsvFeedback("episode_csv_too_large");
      return;
    }
    setCsvFeedback(null);
    csvMutation.mutate(csv);
  }

  return (
    <Stack>
      <Title order={1}>{t("manual.edit.title")}</Title>
      <Modal
        onClose={() => setConfirmationToken(null)}
        opened={confirmationToken !== null}
        title={t("manual.confirmation.title")}
      >
        <Stack>
          <Text>{t("manual.confirmation.description")}</Text>
          <Group justify="flex-end">
            <Button
              onClick={() => setConfirmationToken(null)}
              variant="default"
            >
              {t("manual.confirmation.cancel")}
            </Button>
            <Button
              loading={confirmationMutation.isPending}
              onClick={() => {
                if (confirmationToken !== null) {
                  confirmationMutation.mutate(confirmationToken);
                }
              }}
            >
              {t("manual.confirmation.confirm")}
            </Button>
          </Group>
        </Stack>
      </Modal>
      {feedbackCode ? (
        <Text role="alert">
          {t(`errors.${feedbackCode}`, {
            defaultValue: t("errors.unexpected_response"),
          })}
        </Text>
      ) : null}
      <ManualEditor
        collectionId={collectionId}
        collections={collections}
        document={document}
        onCollectionIdChange={setCollectionId}
        onDocumentChange={setDocument}
        onSubmit={(editorDocument) => mutation.mutate(editorDocument)}
        showCollection={false}
      />
      {item.kind === "series" ? (
        <Stack>
          <Title order={2}>{t("manual.csv.title")}</Title>
          <Text>{t("manual.csv.description")}</Text>
          {csvFeedback ? (
            <Text role="alert">
              {t(`errors.${csvFeedback}`, {
                defaultValue: t("errors.unexpected_response"),
              })}
            </Text>
          ) : null}
          <FileInput
            accept="text/csv,.csv"
            clearable
            label={t("manual.csv.loadFile")}
            onChange={(file) => {
              if (!file) return;
              void file.text().then((source) => {
                setCsvFeedback(null);
                setCsv(source);
              });
            }}
          />
          <Textarea
            label={t("manual.csv.source")}
            onChange={(event) => {
              setCsvFeedback(null);
              setCsv(event.currentTarget.value);
            }}
            rows={8}
            value={csv}
          />
          <Button loading={csvMutation.isPending} onClick={submitCsv}>
            {t("manual.csv.submit")}
          </Button>
        </Stack>
      ) : null}
    </Stack>
  );
}

export function ManualEditPage() {
  const { client, session } = useControl();
  const { t } = useTranslation();
  const { itemId = "" } = useParams();
  const itemQuery = useQuery({
    queryKey: ["control", "media-item", itemId, session.metadata_locale],
    queryFn: ({ signal }) =>
      client.getMediaItem(itemId, session.metadata_locale, signal),
    enabled: itemId.length > 0,
  });
  const collectionsQuery = useQuery({
    queryKey: ["control", "collections", "manual-edit"],
    queryFn: ({ signal }) => client.listCollections(signal),
  });

  if (itemQuery.isPending || collectionsQuery.isPending) {
    return <Loader aria-label={t("detail.loading")} />;
  }
  if (itemQuery.isError || collectionsQuery.isError) {
    return <Text role="alert">{t("errors.unexpected_response")}</Text>;
  }
  if (itemQuery.data.provider_key !== "manual") {
    return <Text role="alert">{t("manual.edit.nonManual")}</Text>;
  }
  return (
    <ManualEditForm
      collections={collectionsQuery.data.items}
      item={itemQuery.data}
    />
  );
}
