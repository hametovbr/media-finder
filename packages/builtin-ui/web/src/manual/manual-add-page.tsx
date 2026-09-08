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
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useBlocker, useNavigate } from "react-router";

import { ControlFailure } from "../api/control-client";
import type { components } from "../api/control.generated";
import { useControl } from "../api/control-provider";
import { ManualEditor } from "./manual-editor";
import {
  createManualDocument,
  createManualRawLists,
  type ManualEditorDocument,
  type ManualRawLists,
  manualDraftEquals,
  projectManualDocument,
  withManualRowKeys,
} from "./manual-document";

type ManualDocument = components["schemas"]["ManualDocumentV1"];
type ManualImportRequest = components["schemas"]["ManualImportRequest"];
type DraftReview = {
  draft: "json" | "structured";
  locale: "en" | "ru";
  request: ManualImportRequest;
};

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
  const [initialRawLists] = useState<ManualRawLists>(() =>
    createManualRawLists(document),
  );
  const [rawLists, setRawLists] = useState<ManualRawLists>(initialRawLists);
  const [initialDocument] = useState<ManualEditorDocument>(document);
  const [initialCollectionId] = useState<string | null>(null);
  const [collectionId, setCollectionId] = useState<string | null>(null);
  const [feedbackCode, setFeedbackCode] = useState<string | null>(null);
  const [mode, setMode] = useState<"structured" | "json">("structured");
  const [jsonSource, setJsonSource] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [draftReview, setDraftReview] = useState<DraftReview | null>(null);
  const [confirmationToken, setConfirmationToken] = useState<string | null>(
    null,
  );
  const [operation, setOperation] = useState<
    "idle" | "reading" | "submitting" | "reviewing" | "confirming"
  >("idle");
  const [jsonReadError, setJsonReadError] = useState<string | null>(null);
  const operationRef = useRef(operation);
  const operationLocale = useRef<string | null>(null);
  const allowFinishNavigation = useRef(false);
  const finishDestination = useRef<string | null>(null);
  const editorReview = useRef(false);
  const jsonReadGeneration = useRef(0);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      jsonReadGeneration.current += 1;
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
    ) || jsonSource.length > 0;
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
  const collectionsQuery = useQuery({
    queryKey: ["control", "collections", "manual-add"],
    queryFn: ({ signal }) => client.listCollections(signal),
  });
  const createMutation = useMutation({
    retry: false,
    mutationFn: (request: ManualImportRequest) => client.importManual(request),
    onSuccess: async (item) => {
      if (!mounted.current) return;
      setFeedbackCode(null);
      setConfirmationToken(null);
      await queryClient.invalidateQueries({ queryKey: ["control", "catalog"] });
      if (!mounted.current) return;
      queryClient.setQueryData(
        [
          "control",
          "media-item",
          item.id,
          operationLocale.current ?? session.metadata_locale,
        ],
        item,
      );
      allowFinishNavigation.current = true;
      finishDestination.current = `/items/${encodeURIComponent(item.id)}`;
      void navigate(finishDestination.current);
    },
    onError: (error) => {
      if (!mounted.current) return;
      if (
        error instanceof ControlFailure &&
        error.code === "confirmation_required" &&
        error.confirmationToken !== null
      ) {
        setFeedbackCode(null);
        setConfirmationToken(error.confirmationToken);
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
    onSuccess: async (item) => {
      if (!mounted.current) return;
      setConfirmationToken(null);
      setFeedbackCode(null);
      await queryClient.invalidateQueries({ queryKey: ["control", "catalog"] });
      if (!mounted.current) return;
      queryClient.setQueryData(
        [
          "control",
          "media-item",
          item.id,
          operationLocale.current ?? session.metadata_locale,
        ],
        item,
      );
      allowFinishNavigation.current = true;
      finishDestination.current = `/items/${encodeURIComponent(item.id)}`;
      void navigate(finishDestination.current);
    },
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

  function startCreate(
    request: ManualImportRequest,
    locale = session.metadata_locale,
  ) {
    operationLocale.current = locale;
    setPageOperation("submitting");
    createMutation.mutate(request);
  }

  function reviewCreate(
    request: ManualImportRequest,
    draft: DraftReview["draft"],
  ) {
    if (operationRef.current !== "idle" || navigationReview) return;
    setDraftReview({ draft, locale: session.metadata_locale, request });
    setPageOperation("reviewing");
  }

  function submitJson() {
    if (operationRef.current !== "idle" || navigationReview) return;
    const result = parseManualJson(jsonSource);
    setJsonError(result.error);
    if (!result.document) return;
    setFeedbackCode(null);
    const request = { collection_id: collectionId, document: result.document };
    if (
      !manualDraftEquals(
        initialDocument,
        document,
        initialRawLists,
        rawLists,
        collectionId,
        collectionId,
      )
    ) {
      reviewCreate(request, "structured");
      return;
    }
    startCreate(request);
  }

  function loadJsonFile(file: File | null) {
    if (navigationReview) return;
    jsonReadGeneration.current += 1;
    const generation = jsonReadGeneration.current;
    if (!file) {
      if (operationRef.current === "reading") setPageOperation("idle");
      return;
    }
    if (operationRef.current !== "idle" && operationRef.current !== "reading") {
      return;
    }
    if (file.size > MAX_JSON_BYTES) {
      setJsonError("manual.validation.jsonTooLarge");
      if (operationRef.current === "reading") setPageOperation("idle");
      return;
    }
    setJsonReadError(null);
    setPageOperation("reading");
    void file.text().then(
      (source) => {
        if (
          !mounted.current ||
          generation !== jsonReadGeneration.current ||
          operationRef.current !== "reading"
        )
          return;
        setJsonError(null);
        setJsonSource(source);
        setPageOperation("idle");
      },
      () => {
        if (
          !mounted.current ||
          generation !== jsonReadGeneration.current ||
          operationRef.current !== "reading"
        )
          return;
        setJsonReadError("manual.operation.fileReadFailed");
        setPageOperation("idle");
      },
    );
  }

  const dialogActionStyle = { height: "auto", minHeight: "2.25rem" } as const;
  const dialogActionStyles = { label: { whiteSpace: "normal" } } as const;

  return (
    <Stack>
      <Title order={1}>{t("routes.manual")}</Title>
      <Text>{t("manual.introduction")}</Text>
      <Group>
        <Button
          aria-pressed={mode === "structured"}
          disabled={locked}
          onClick={() => {
            if (locked) return;
            jsonReadGeneration.current += 1;
            if (operationRef.current === "reading") setPageOperation("idle");
            setMode("structured");
          }}
          variant={mode === "structured" ? "filled" : "default"}
        >
          {t("manual.modes.structured")}
        </Button>
        <Button
          aria-pressed={mode === "json"}
          disabled={locked}
          onClick={() => {
            if (locked) return;
            setMode("json");
          }}
          variant={mode === "json" ? "filled" : "default"}
        >
          {t("manual.modes.json")}
        </Button>
      </Group>
      <Modal
        closeOnEscape={operation !== "confirming"}
        onClose={() => {
          if (operationRef.current !== "reviewing") return;
          setConfirmationToken(null);
          setPageOperation("idle");
        }}
        opened={confirmationToken !== null}
        withCloseButton={operation !== "confirming"}
        closeOnClickOutside={operation !== "confirming"}
        title={t("manual.confirmation.title")}
      >
        <Stack>
          <Text>{t("manual.confirmation.description")}</Text>
          <Group justify="flex-end">
            <Button
              onClick={() => {
                if (operationRef.current !== "reviewing") return;
                setConfirmationToken(null);
                setPageOperation("idle");
              }}
              disabled={operation !== "reviewing"}
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
                draft: t(`manual.drafts.${draftReview?.draft}`),
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
                  startCreate(request, draftReview.locale);
                }}
              >
                {t("manual.drafts.continue")}
              </Button>
            </Group>
          </Stack>
        ) : null}
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
      {collectionsQuery.isPending ? (
        <Loader aria-label={t("manual.loadingCollections")} />
      ) : collectionsQuery.isError ? (
        <Text role="alert">{t("errors.unexpected_response")}</Text>
      ) : mode === "json" ? (
        <Stack>
          {jsonError ? <Text role="alert">{t(jsonError)}</Text> : null}
          <Select
            clearable
            disabled={locked}
            data={collectionsQuery.data.items.map((collection) => ({
              label: collection.name,
              value: collection.id,
            }))}
            label={t("manual.fields.collection")}
            onChange={(nextCollectionId) => {
              if (navigationReview) return;
              setCollectionId(nextCollectionId);
            }}
            placeholder={t("manual.fields.noCollection")}
            value={collectionId}
          />
          <FileInput
            accept="application/json,.json"
            clearable
            disabled={locked}
            label={t("manual.json.loadFile")}
            onChange={loadJsonFile}
          />
          <Textarea
            disabled={locked}
            label={t("manual.json.source")}
            minRows={12}
            onChange={(event) => {
              if (navigationReview) return;
              jsonReadGeneration.current += 1;
              if (operationRef.current === "reading") setPageOperation("idle");
              setJsonError(null);
              setJsonReadError(null);
              setJsonSource(event.currentTarget.value);
            }}
            value={jsonSource}
          />
          {jsonReadError ? <Text role="alert">{t(jsonReadError)}</Text> : null}
          <Button
            disabled={operation !== "idle"}
            loading={operation === "submitting"}
            onClick={submitJson}
          >
            {t("manual.json.submit")}
          </Button>
        </Stack>
      ) : (
        <ManualEditor
          collectionId={collectionId}
          collections={collectionsQuery.data.items}
          document={document}
          disabled={locked}
          onCollectionIdChange={setCollectionId}
          onDocumentChange={setDocument}
          onReviewChange={onEditorReviewChange}
          onRawListsChange={setRawLists}
          onSubmit={(editorDocument, requestedCollectionId) =>
            (() => {
              const request = {
                collection_id: requestedCollectionId,
                document: projectManualDocument(
                  editorDocument,
                  initialRawLists,
                  rawLists,
                ),
              };
              if (jsonSource.length > 0) reviewCreate(request, "json");
              else if (operationRef.current === "idle" && !navigationReview)
                startCreate(request);
            })()
          }
          rawLists={rawLists}
        />
      )}
    </Stack>
  );
}
