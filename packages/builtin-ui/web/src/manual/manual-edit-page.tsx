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
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useBlocker, useNavigate, useParams } from "react-router";

import { ControlFailure } from "../api/control-client";
import type { components } from "../api/control.generated";
import { useControl } from "../api/control-provider";
import { ManualEditor } from "./manual-editor";
import {
  manualDocumentFromItem,
  type ManualEditorDocument,
  createManualRawLists,
  type ManualRawLists,
  manualDraftEquals,
  projectManualDocument,
  withManualRowKeys,
} from "./manual-document";

type MediaItem = components["schemas"]["MediaItemDetail"];
type Collection = components["schemas"]["CollectionView"];
type EditRequest = {
  document: components["schemas"]["ManualDocumentV1"];
  id: string;
  locale: "en" | "ru";
};
type CsvRequest = { id: string; locale: "en" | "ru"; source: string };
type DraftReview = { request: EditRequest };
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
  const [initialDocument] = useState<ManualEditorDocument>(document);
  const [initialCollectionId] = useState<string | null>(
    item.collection_id ?? null,
  );
  const [initialRawLists] = useState<ManualRawLists>(() =>
    createManualRawLists(document),
  );
  const [rawLists, setRawLists] = useState<ManualRawLists>(initialRawLists);
  const [feedbackCode, setFeedbackCode] = useState<string | null>(null);
  const [confirmationToken, setConfirmationToken] = useState<string | null>(
    null,
  );
  const [csv, setCsv] = useState("");
  const [csvFeedback, setCsvFeedback] = useState<string | null>(null);
  const [csvReadError, setCsvReadError] = useState<string | null>(null);
  const [draftReview, setDraftReview] = useState<DraftReview | null>(null);
  const [resetStructuredReview, setResetStructuredReview] = useState(false);
  const [operation, setOperation] = useState<
    "idle" | "reading" | "submitting" | "reviewing" | "confirming"
  >("idle");
  const operationRef = useRef(operation);
  const operationLocale = useRef<string | null>(null);
  const allowFinishNavigation = useRef(false);
  const finishDestination = useRef<string | null>(null);
  const csvReadGeneration = useRef(0);
  const mounted = useRef(false);
  const editorReview = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      csvReadGeneration.current += 1;
    };
  }, []);
  function setPageOperation(
    next: "idle" | "reading" | "submitting" | "reviewing" | "confirming",
  ) {
    operationRef.current = next;
    setOperation(next);
  }
  function onEditorReviewChange(reviewing: boolean): boolean | void {
    if (reviewing) {
      if (operationRef.current !== "idle" || navigationReview) return false;
      editorReview.current = true;
      setPageOperation("reviewing");
      return true;
    }
    if (editorReview.current && operationRef.current === "reviewing") {
      editorReview.current = false;
      setPageOperation("idle");
    }
  }
  const dirty =
    !manualDraftEquals(
      initialDocument,
      document,
      initialRawLists,
      rawLists,
      initialCollectionId,
      collectionId,
    ) || csv.length > 0;
  const blocker = useBlocker(({ nextLocation }) => {
    if (
      allowFinishNavigation.current &&
      nextLocation.pathname === finishDestination.current
    ) {
      allowFinishNavigation.current = false;
      return false;
    }
    return operationRef.current !== "idle" || dirty;
  });
  const navigationReview =
    blocker.state === "blocked" && operationRef.current === "idle";
  const locked =
    navigationReview || (operation !== "idle" && operation !== "reading");
  useEffect(() => {
    if (blocker.state === "blocked" && operationRef.current !== "idle") {
      blocker.reset?.();
    }
  }, [blocker, operation]);
  useEffect(() => {
    if (!dirty && operation === "idle") return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    globalThis.addEventListener("beforeunload", onBeforeUnload);
    return () => globalThis.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty, operation]);
  async function finish(updated: MediaItem, locale = operationLocale.current) {
    if (!mounted.current) return;
    setConfirmationToken(null);
    setFeedbackCode(null);
    await queryClient.invalidateQueries({ queryKey: ["control", "catalog"] });
    if (!mounted.current) return;
    queryClient.setQueryData(
      ["control", "media-item", item.id, locale ?? session.metadata_locale],
      updated,
    );
    allowFinishNavigation.current = true;
    finishDestination.current = `/items/${encodeURIComponent(item.id)}`;
    void navigate(finishDestination.current);
  }
  const mutation = useMutation({
    retry: false,
    mutationFn: (request: EditRequest) =>
      client.editManual(request.id, request.document),
    onSuccess: (updated, request) => finish(updated, request.locale),
    onError: (error) => {
      if (!mounted.current) return;
      if (
        error instanceof ControlFailure &&
        error.code === "confirmation_required" &&
        error.confirmationToken !== null
      ) {
        setConfirmationToken(error.confirmationToken);
        setFeedbackCode(null);
        setPageOperation("reviewing");
        return;
      }
      setFeedbackCode(
        error instanceof ControlFailure ? error.code : "unexpected_response",
      );
      setPageOperation("idle");
    },
  });
  const confirmationMutation = useMutation({
    retry: false,
    mutationFn: (token: string) => client.confirmManual(token),
    onSuccess: (updated) => finish(updated),
    onError: (error) => {
      if (!mounted.current) return;
      setConfirmationToken(null);
      setFeedbackCode(
        error instanceof ControlFailure && error.code === "selection_expired"
          ? "manual_confirmation_expired"
          : error instanceof ControlFailure
            ? error.code
            : "unexpected_response",
      );
      setPageOperation("idle");
    },
  });
  const csvMutation = useMutation({
    retry: false,
    mutationFn: (request: CsvRequest) =>
      client.importEpisodes(request.id, request.source),
    onSuccess: (updated, request) => finish(updated, request.locale),
    onError: (error) => {
      if (!mounted.current) return;
      setCsvFeedback(
        error instanceof ControlFailure ? error.code : "unexpected_response",
      );
      setPageOperation("idle");
    },
  });

  const structuredDirty = !manualDraftEquals(
    initialDocument,
    document,
    initialRawLists,
    rawLists,
    initialCollectionId,
    collectionId,
  );

  function startEdit(request: EditRequest) {
    operationLocale.current = request.locale;
    setPageOperation("submitting");
    mutation.mutate(request);
  }

  function submitStructured(editorDocument: ManualEditorDocument) {
    if (operationRef.current !== "idle" || navigationReview) return;
    const request = {
      document: projectManualDocument(
        editorDocument,
        initialRawLists,
        rawLists,
      ),
      id: item.id,
      locale: session.metadata_locale,
    };
    if (csv.length > 0) {
      setDraftReview({ request });
      setPageOperation("reviewing");
      return;
    }
    startEdit(request);
  }

  function submitCsv() {
    if (operationRef.current !== "idle" || navigationReview) return;
    if (structuredDirty) {
      setCsvFeedback("manual.csv.unsaved");
      return;
    }
    if (csv.length === 0) {
      setCsvFeedback("episode_csv_empty");
      return;
    }
    if (new TextEncoder().encode(csv).byteLength > MAX_CSV_BYTES) {
      setCsvFeedback("episode_csv_too_large");
      return;
    }
    setCsvFeedback(null);
    operationLocale.current = session.metadata_locale;
    setPageOperation("submitting");
    csvMutation.mutate({
      id: item.id,
      locale: session.metadata_locale,
      source: csv,
    });
  }

  function loadCsvFile(file: File | null) {
    if (navigationReview) return;
    csvReadGeneration.current += 1;
    const generation = csvReadGeneration.current;
    if (!file) {
      if (operationRef.current === "reading") setPageOperation("idle");
      return;
    }
    if (operationRef.current !== "idle" && operationRef.current !== "reading") {
      return;
    }
    if (file.size > MAX_CSV_BYTES) {
      setCsvFeedback("episode_csv_too_large");
      if (operationRef.current === "reading") setPageOperation("idle");
      return;
    }
    setCsvReadError(null);
    setPageOperation("reading");
    void file.text().then(
      (source) => {
        if (!mounted.current || generation !== csvReadGeneration.current)
          return;
        setCsvFeedback(null);
        setCsv(source);
        setPageOperation("idle");
      },
      () => {
        if (!mounted.current || generation !== csvReadGeneration.current)
          return;
        setCsvReadError("manual.operation.fileReadFailed");
        setPageOperation("idle");
      },
    );
  }

  const dialogActionStyle = { height: "auto", minHeight: "2.25rem" } as const;
  const dialogActionStyles = { label: { whiteSpace: "normal" } } as const;

  return (
    <Stack>
      <Title order={1}>{t("manual.edit.title")}</Title>
      <Modal
        closeOnClickOutside={operation !== "confirming"}
        closeOnEscape={operation !== "confirming"}
        onClose={() => {
          if (operationRef.current !== "reviewing") return;
          setConfirmationToken(null);
          setPageOperation("idle");
        }}
        opened={confirmationToken !== null}
        withCloseButton={operation !== "confirming"}
        title={t("manual.confirmation.title")}
      >
        <Stack>
          <Text>{t("manual.confirmation.description")}</Text>
          <Group justify="flex-end">
            <Button
              disabled={operation !== "reviewing"}
              onClick={() => {
                if (operationRef.current !== "reviewing") return;
                setConfirmationToken(null);
                setPageOperation("idle");
              }}
              variant="default"
            >
              {t("manual.confirmation.cancel")}
            </Button>
            <Button
              loading={operation === "confirming"}
              onClick={() => {
                if (
                  confirmationToken !== null &&
                  operationRef.current === "reviewing"
                ) {
                  setPageOperation("confirming");
                  confirmationMutation.mutate(confirmationToken);
                }
              }}
            >
              {t("manual.confirmation.confirm")}
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Modal
        closeOnClickOutside={false}
        closeOnEscape={false}
        onClose={() => undefined}
        opened={draftReview !== null}
        title={t("manual.drafts.title")}
        returnFocus
        withCloseButton={false}
      >
        {draftReview ? (
          <Stack>
            <Text>
              {t("manual.drafts.description", {
                draft: t("manual.drafts.csv"),
              })}
            </Text>
            <Group justify="flex-end">
              <Button
                data-autofocus
                styles={dialogActionStyles}
                style={dialogActionStyle}
                onClick={() => {
                  setDraftReview(null);
                  setPageOperation("idle");
                }}
                variant="default"
              >
                {t("manual.drafts.cancel")}
              </Button>
              <Button
                styles={dialogActionStyles}
                style={dialogActionStyle}
                onClick={() => {
                  if (!draftReview || operationRef.current !== "reviewing")
                    return;
                  const request = draftReview.request;
                  setDraftReview(null);
                  startEdit(request);
                }}
              >
                {t("manual.drafts.continue")}
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Modal>
      <Modal
        closeOnClickOutside={false}
        closeOnEscape={false}
        onClose={() => undefined}
        opened={resetStructuredReview}
        title={t("manual.csv.discardTitle")}
        returnFocus
        withCloseButton={false}
      >
        <Stack>
          <Text>{t("manual.csv.discardDescription")}</Text>
          <Group justify="flex-end">
            <Button
              data-autofocus
              styles={dialogActionStyles}
              style={dialogActionStyle}
              onClick={() => {
                setResetStructuredReview(false);
                setPageOperation("idle");
              }}
              variant="default"
            >
              {t("manual.drafts.cancel")}
            </Button>
            <Button
              styles={dialogActionStyles}
              style={dialogActionStyle}
              onClick={() => {
                setDocument(initialDocument);
                setRawLists(initialRawLists);
                setCollectionId(initialCollectionId);
                setResetStructuredReview(false);
                setCsvFeedback(null);
                setPageOperation("idle");
              }}
            >
              {t("manual.csv.discardStructured")}
            </Button>
          </Group>
        </Stack>
      </Modal>
      <Modal
        onClose={() => {
          if (navigationReview) blocker.reset?.();
        }}
        opened={navigationReview}
        title={t("manual.navigation.title")}
        returnFocus
        withCloseButton={false}
      >
        <Stack>
          <Text>{t("manual.navigation.description")}</Text>
          <Group justify="flex-end">
            <Button
              data-autofocus
              styles={dialogActionStyles}
              style={dialogActionStyle}
              onClick={() => blocker.reset?.()}
              variant="default"
            >
              {t("manual.navigation.stay")}
            </Button>
            <Button
              color="red"
              styles={dialogActionStyles}
              style={dialogActionStyle}
              onClick={() => {
                blocker.proceed?.();
              }}
            >
              {t("manual.navigation.leave")}
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
      {operation === "submitting" || operation === "confirming" ? (
        <Text role="status">{t("manual.operation.pending")}</Text>
      ) : operation === "reading" ? (
        <Text role="status">{t("manual.operation.reading")}</Text>
      ) : null}
      <ManualEditor
        collectionId={collectionId}
        collections={collections}
        document={document}
        disabled={locked}
        onCollectionIdChange={setCollectionId}
        onDocumentChange={setDocument}
        onRawListsChange={setRawLists}
        onReviewChange={onEditorReviewChange}
        onSubmit={submitStructured}
        showCollection={false}
        rawLists={rawLists}
      />
      {item.kind === "series" ? (
        <Stack>
          <Title order={2}>{t("manual.csv.title")}</Title>
          <Text>{t("manual.csv.description")}</Text>
          {csvFeedback ? (
            <Text role="alert">
              {csvFeedback === "manual.csv.unsaved"
                ? t(csvFeedback)
                : t(`errors.${csvFeedback}`, {
                    defaultValue: t("errors.unexpected_response"),
                  })}
            </Text>
          ) : null}
          {csvReadError ? <Text role="alert">{t(csvReadError)}</Text> : null}
          {csvFeedback === "manual.csv.unsaved" && structuredDirty ? (
            <Button
              disabled={operation !== "idle"}
              onClick={() => {
                if (operationRef.current !== "idle") return;
                setResetStructuredReview(true);
                setPageOperation("reviewing");
              }}
              variant="default"
            >
              {t("manual.csv.discardStructured")}
            </Button>
          ) : null}
          <FileInput
            accept="text/csv,.csv"
            clearable
            disabled={locked}
            label={t("manual.csv.loadFile")}
            onChange={loadCsvFile}
          />
          <Textarea
            disabled={locked}
            label={t("manual.csv.source")}
            onChange={(event) => {
              if (navigationReview) return;
              csvReadGeneration.current += 1;
              if (operationRef.current === "reading") setPageOperation("idle");
              setCsvFeedback(null);
              setCsvReadError(null);
              setCsv(event.currentTarget.value);
            }}
            rows={8}
            value={csv}
          />
          <Button
            disabled={operation !== "idle"}
            loading={operation === "submitting"}
            onClick={submitCsv}
          >
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

  if (!itemQuery.data || !collectionsQuery.data) {
    if (itemQuery.isError || collectionsQuery.isError) {
      return <Text role="alert">{t("errors.unexpected_response")}</Text>;
    }
    return <Loader aria-label={t("detail.loading")} />;
  }
  if (itemQuery.data.provider_key !== "manual") {
    return <Text role="alert">{t("manual.edit.nonManual")}</Text>;
  }
  return (
    <ManualEditForm
      key={itemQuery.data.id}
      collections={collectionsQuery.data.items}
      item={itemQuery.data}
    />
  );
}
