import {
  Button,
  FileInput,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Text,
  Textarea,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { ControlFailure } from "../api/control-client";
import type { components } from "../api/control.generated";
import { useControl } from "../api/control-provider";
import { ManualEditor } from "./manual-editor";
import {
  createManualDocument,
  type ManualEditorDocument,
  toManualDocument,
  withManualRowKeys,
} from "./manual-document";

type ManualDocument = components["schemas"]["ManualDocumentV1"];
type ManualImportRequest = components["schemas"]["ManualImportRequest"];

const MAX_JSON_BYTES = 1024 * 1024;

function parseManualJson(
  source: string,
):
  | { document: ManualDocument; error: null }
  | { document: null; error: string } {
  if (new TextEncoder().encode(source).byteLength > MAX_JSON_BYTES) {
    return { document: null, error: "manual.validation.jsonTooLarge" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(source);
  } catch {
    return { document: null, error: "manual.validation.jsonSyntax" };
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    return { document: null, error: "manual.validation.jsonObject" };
  }
  if (!("schema_version" in parsed) || parsed.schema_version !== "1") {
    return { document: null, error: "manual.validation.jsonVersion" };
  }
  return { document: parsed as ManualDocument, error: null };
}

export function ManualAddPage() {
  const { client, session } = useControl();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [document, setDocument] = useState<ManualEditorDocument>(() =>
    withManualRowKeys(
      createManualDocument("movie", session.metadata_locale),
      () => globalThis.crypto.randomUUID(),
    ),
  );
  const [collectionId, setCollectionId] = useState<string | null>(null);
  const [feedbackCode, setFeedbackCode] = useState<string | null>(null);
  const [mode, setMode] = useState<"structured" | "json">("structured");
  const [jsonSource, setJsonSource] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [confirmationToken, setConfirmationToken] = useState<string | null>(
    null,
  );
  const collectionsQuery = useQuery({
    queryKey: ["control", "collections", "manual-add"],
    queryFn: ({ signal }) => client.listCollections(signal),
  });
  const createMutation = useMutation({
    mutationFn: (request: ManualImportRequest) => client.importManual(request),
    onSuccess: async (item) => {
      setFeedbackCode(null);
      setConfirmationToken(null);
      await queryClient.invalidateQueries({ queryKey: ["control", "catalog"] });
      queryClient.setQueryData(
        ["control", "media-item", item.id, session.metadata_locale],
        item,
      );
      void navigate(`/items/${encodeURIComponent(item.id)}`);
    },
    onError: (error) => {
      if (
        error instanceof ControlFailure &&
        error.code === "confirmation_required" &&
        error.confirmationToken !== null
      ) {
        setFeedbackCode(null);
        setConfirmationToken(error.confirmationToken);
        return;
      }
      setFeedbackCode(
        error instanceof ControlFailure ? error.code : "unexpected_response",
      );
    },
  });
  const confirmationMutation = useMutation({
    mutationFn: (token: string) => client.confirmManual(token),
    onSuccess: async (item) => {
      setConfirmationToken(null);
      setFeedbackCode(null);
      await queryClient.invalidateQueries({ queryKey: ["control", "catalog"] });
      queryClient.setQueryData(
        ["control", "media-item", item.id, session.metadata_locale],
        item,
      );
      void navigate(`/items/${encodeURIComponent(item.id)}`);
    },
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

  function submitJson() {
    const result = parseManualJson(jsonSource);
    setJsonError(result.error);
    if (!result.document) return;
    setFeedbackCode(null);
    createMutation.mutate({
      collection_id: collectionId,
      document: result.document,
    });
  }

  return (
    <Stack>
      <Title order={1}>{t("routes.manual")}</Title>
      <Text>{t("manual.introduction")}</Text>
      <Group>
        <Button
          aria-pressed={mode === "structured"}
          onClick={() => setMode("structured")}
          variant={mode === "structured" ? "filled" : "default"}
        >
          {t("manual.modes.structured")}
        </Button>
        <Button
          aria-pressed={mode === "json"}
          onClick={() => setMode("json")}
          variant={mode === "json" ? "filled" : "default"}
        >
          {t("manual.modes.json")}
        </Button>
      </Group>
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
      {collectionsQuery.isPending ? (
        <Loader aria-label={t("manual.loadingCollections")} />
      ) : collectionsQuery.isError ? (
        <Text role="alert">{t("errors.unexpected_response")}</Text>
      ) : mode === "json" ? (
        <Stack>
          {jsonError ? <Text role="alert">{t(jsonError)}</Text> : null}
          <Select
            clearable
            data={collectionsQuery.data.items.map((collection) => ({
              label: collection.name,
              value: collection.id,
            }))}
            label={t("manual.fields.collection")}
            onChange={setCollectionId}
            placeholder={t("manual.fields.noCollection")}
            value={collectionId}
          />
          <FileInput
            accept="application/json,.json"
            clearable
            label={t("manual.json.loadFile")}
            onChange={(file) => {
              if (!file) return;
              void file.text().then((source) => {
                setJsonError(null);
                setJsonSource(source);
              });
            }}
          />
          <Textarea
            label={t("manual.json.source")}
            minRows={12}
            onChange={(event) => {
              setJsonError(null);
              setJsonSource(event.currentTarget.value);
            }}
            value={jsonSource}
          />
          <Button loading={createMutation.isPending} onClick={submitJson}>
            {t("manual.json.submit")}
          </Button>
        </Stack>
      ) : (
        <ManualEditor
          collectionId={collectionId}
          collections={collectionsQuery.data.items}
          document={document}
          onCollectionIdChange={setCollectionId}
          onDocumentChange={setDocument}
          onSubmit={(editorDocument, requestedCollectionId) =>
            createMutation.mutate({
              collection_id: requestedCollectionId,
              document: toManualDocument(editorDocument),
            })
          }
        />
      )}
    </Stack>
  );
}
