import {
  Alert,
  Box,
  Button,
  Collapse,
  Fieldset,
  Group,
  NumberInput,
  Modal,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  UnstyledButton,
} from "@mantine/core";
import {
  type FormEvent,
  type MouseEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import type { components } from "../api/control.generated";
import type {
  ManualEditorDocument,
  ManualEditorEpisode,
  ManualEditorSeason,
  ManualRawLists,
} from "./manual-document";

type Collection = components["schemas"]["CollectionView"];
type MediaKind = components["schemas"]["MediaKind"];

type DestructiveReview =
  | {
      episodeRowKey: string;
      episodeNumber: number;
      kind: "episode";
      seasonRowKey: string;
      descendantCount: 1;
    }
  | {
      kind: "season";
      seasonNumber: number;
      seasonRowKey: string;
      descendantCount: number;
    }
  | {
      episodeCount: number;
      kind: "seriesToMovie";
      seasonCount: number;
      descendantCount: number;
    };

type ReviewFocus =
  | { kind: "initiator"; element: HTMLElement }
  | { kind: "addEpisode"; seasonRowKey: string }
  | { kind: "addSeason" }
  | { kind: "kindSelector" };

export interface ManualEditorProps {
  collectionId: string | null;
  collections: Collection[];
  disabled?: boolean;
  document: ManualEditorDocument;
  onCollectionIdChange: (collectionId: string | null) => void;
  onDocumentChange: (document: ManualEditorDocument) => void;
  onReviewChange?: (reviewing: boolean) => boolean | void;
  onRawListsChange: (rawLists: ManualRawLists) => void;
  onSubmit: (
    document: ManualEditorDocument,
    collectionId: string | null,
  ) => void;
  rawLists: ManualRawLists;
  showCollection?: boolean;
}

function nullableNumber(value: number | string): number | null {
  return typeof value === "number" ? value : null;
}

function createRowKey(): string {
  return globalThis.crypto.randomUUID();
}

const wrappingButtonStyle = {
  height: "auto",
  minHeight: "2.25rem",
};
const wrappingButtonLabelStyle = {
  lineHeight: 1.25,
  whiteSpace: "normal" as const,
};

export function ManualEditor({
  collectionId,
  collections,
  disabled = false,
  document,
  onCollectionIdChange,
  onDocumentChange,
  onReviewChange,
  onRawListsChange,
  onSubmit,
  rawLists,
  showCollection = true,
}: ManualEditorProps) {
  const { t } = useTranslation();
  const titleInput = useRef<HTMLInputElement>(null);
  const kindInput = useRef<HTMLInputElement>(null);
  const addSeasonButton = useRef<HTMLButtonElement>(null);
  const addEpisodeButtons = useRef(new Map<string, HTMLButtonElement>());
  const reviewRef = useRef<DestructiveReview | null>(null);
  const reviewInitiatorRef = useRef<HTMLElement | null>(null);
  const reviewFocusRef = useRef<ReviewFocus | null>(null);
  const onReviewChangeRef = useRef(onReviewChange);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [review, setReview] = useState<DestructiveReview | null>(null);
  const [secondaryFieldsOpen, setSecondaryFieldsOpen] = useState(false);
  const activeTitle = document.titles[document.locale] ?? "";
  const identityLocked = document.external_id !== undefined;
  const controlsDisabled = disabled || review !== null;
  const secondaryFieldsId = "manual-editor-secondary-fields";
  const episodeCount = document.seasons.reduce(
    (count, season) => count + season.episodes.length,
    0,
  );

  onReviewChangeRef.current = onReviewChange;

  useEffect(() => {
    return () => {
      if (reviewRef.current !== null) {
        reviewRef.current = null;
        onReviewChangeRef.current?.(false);
      }
    };
  }, []);

  function updateDocument(
    update: Partial<ManualEditorDocument>,
    allowDuringReview = false,
  ) {
    if (!allowDuringReview && (disabled || reviewRef.current !== null)) {
      return;
    }
    onDocumentChange({ ...document, ...update });
  }

  function updateSeason(rowKey: string, update: Partial<ManualEditorSeason>) {
    updateDocument({
      seasons: document.seasons.map((season) =>
        season.rowKey === rowKey ? { ...season, ...update } : season,
      ),
    });
  }

  function updateEpisode(
    seasonRowKey: string,
    episodeRowKey: string,
    update: Partial<ManualEditorEpisode>,
  ) {
    const season = document.seasons.find(
      (candidate) => candidate.rowKey === seasonRowKey,
    );
    if (!season) return;
    updateSeason(seasonRowKey, {
      episodes: season.episodes.map((episode) =>
        episode.rowKey === episodeRowKey ? { ...episode, ...update } : episode,
      ),
    });
  }

  function addSeason() {
    const nextNumber =
      Math.max(0, ...document.seasons.map(({ number }) => number)) + 1;
    updateDocument({
      seasons: [
        ...document.seasons,
        {
          episodes: [],
          number: nextNumber,
          plot: null,
          provider_ids: {},
          rowKey: createRowKey(),
          title: null,
        },
      ],
    });
  }

  function addEpisode(season: ManualEditorSeason) {
    const nextNumber =
      Math.max(0, ...season.episodes.map(({ number }) => number)) + 1;
    updateSeason(season.rowKey, {
      episodes: [
        ...season.episodes,
        {
          air_date: null,
          number: nextNumber,
          ordering: null,
          plot: null,
          provider_ids: {},
          rowKey: createRowKey(),
          runtime_minutes: null,
          title: "",
        },
      ],
    });
  }

  function selectKind(kind: MediaKind) {
    if (disabled || reviewRef.current !== null || identityLocked) return;
    if (kind === "movie" && document.seasons.length > 0) {
      const episodeCount = document.seasons.reduce(
        (count, season) => count + season.episodes.length,
        0,
      );
      openReview(
        {
          episodeCount,
          kind: "seriesToMovie",
          seasonCount: document.seasons.length,
          descendantCount: episodeCount,
        },
        kindInput.current ?? globalThis.document.activeElement,
        { kind: "kindSelector" },
      );
      return;
    }
    updateDocument({
      kind,
      seasons: kind === "movie" ? [] : document.seasons,
    });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (disabled || reviewRef.current !== null) return;
    if (!activeTitle.trim()) {
      setValidationError(t("manual.validation.titleRequired"));
      titleInput.current?.focus();
      return;
    }
    setValidationError(null);
    onSubmit(document, collectionId);
  }

  function requestEpisodeRemoval(
    season: ManualEditorSeason,
    episode: ManualEditorEpisode,
    event: MouseEvent<HTMLButtonElement>,
  ) {
    if (disabled || reviewRef.current !== null) return;
    openReview(
      {
        episodeRowKey: episode.rowKey,
        episodeNumber: episode.number,
        kind: "episode",
        seasonRowKey: season.rowKey,
        descendantCount: 1,
      },
      event.currentTarget,
      { kind: "addEpisode", seasonRowKey: season.rowKey },
    );
  }

  function requestSeasonRemoval(
    season: ManualEditorSeason,
    event: MouseEvent<HTMLButtonElement>,
  ) {
    if (disabled || reviewRef.current !== null) return;
    openReview(
      {
        kind: "season",
        seasonNumber: season.number,
        seasonRowKey: season.rowKey,
        descendantCount: season.episodes.length,
      },
      event.currentTarget,
      { kind: "addSeason" },
    );
  }

  function openReview(
    nextReview: DestructiveReview,
    initiator: Element | null,
    afterConfirm: ReviewFocus,
  ) {
    if (disabled || reviewRef.current !== null) return;
    if (onReviewChangeRef.current?.(true) === false) return;
    reviewRef.current = nextReview;
    reviewInitiatorRef.current =
      initiator instanceof HTMLElement ? initiator : null;
    reviewFocusRef.current = afterConfirm;
    setReview(nextReview);
  }

  function closeReview() {
    if (reviewRef.current === null) return;
    reviewRef.current = null;
    setReview(null);
    onReviewChangeRef.current?.(false);
  }

  function cancelReview() {
    if (reviewRef.current === null) return;
    const element =
      reviewInitiatorRef.current ?? kindInput.current ?? titleInput.current;
    reviewFocusRef.current = element ? { element, kind: "initiator" } : null;
    closeReview();
  }

  function confirmReview() {
    const pendingReview = reviewRef.current;
    if (pendingReview === null) return;

    if (pendingReview.kind === "episode") {
      const season = document.seasons.find(
        (candidate) => candidate.rowKey === pendingReview.seasonRowKey,
      );
      if (
        season?.episodes.some(
          ({ rowKey }) => rowKey === pendingReview.episodeRowKey,
        )
      ) {
        const seasons = document.seasons.map((candidate) =>
          candidate.rowKey === pendingReview.seasonRowKey
            ? {
                ...candidate,
                episodes: candidate.episodes.filter(
                  ({ rowKey }) => rowKey !== pendingReview.episodeRowKey,
                ),
              }
            : candidate,
        );
        reviewFocusRef.current = {
          kind: "addEpisode",
          seasonRowKey: pendingReview.seasonRowKey,
        };
        closeReview();
        updateDocument({ seasons }, true);
        return;
      }
    }

    if (pendingReview.kind === "season") {
      if (
        document.seasons.some(
          ({ rowKey }) => rowKey === pendingReview.seasonRowKey,
        )
      ) {
        reviewFocusRef.current = { kind: "addSeason" };
        closeReview();
        updateDocument(
          {
            seasons: document.seasons.filter(
              ({ rowKey }) => rowKey !== pendingReview.seasonRowKey,
            ),
          },
          true,
        );
        return;
      }
    }

    if (pendingReview.kind === "seriesToMovie") {
      reviewFocusRef.current = { kind: "kindSelector" };
      closeReview();
      updateDocument({ kind: "movie", seasons: [] }, true);
      return;
    }

    closeReview();
  }

  function restoreReviewFocus() {
    const focus = reviewFocusRef.current;
    reviewFocusRef.current = null;
    reviewInitiatorRef.current = null;
    if (!focus) return;
    if (focus.kind === "initiator") {
      focus.element.focus();
      return;
    }
    if (focus.kind === "addSeason") {
      addSeasonButton.current?.focus();
      return;
    }
    if (focus.kind === "kindSelector") {
      kindInput.current?.focus();
      return;
    }
    addEpisodeButtons.current.get(focus.seasonRowKey)?.focus();
  }

  return (
    <Box
      component="form"
      data-testid="manual-editor-layout"
      onSubmit={submit}
      style={{ minWidth: 0, width: "100%" }}
    >
      <fieldset
        disabled={controlsDisabled}
        style={{ border: 0, margin: 0, minInlineSize: 0, padding: 0 }}
      >
        <Stack gap="md">
          {validationError ? (
            <Alert role="alert">{validationError}</Alert>
          ) : null}

          {identityLocked ? (
            <>
              <TextInput
                label={t("manual.fields.externalId")}
                readOnly
                value={document.external_id ?? ""}
              />
              <TextInput
                label={t("manual.fields.kind")}
                readOnly
                value={t(`mediaKind.${document.kind}`)}
              />
            </>
          ) : (
            <Select
              allowDeselect={false}
              data={[
                { label: t("mediaKind.movie"), value: "movie" },
                { label: t("mediaKind.series"), value: "series" },
              ]}
              disabled={controlsDisabled}
              label={t("manual.fields.kind")}
              onChange={(value) => {
                if (disabled || reviewRef.current !== null) return;
                if (value === "movie" || value === "series") selectKind(value);
              }}
              ref={kindInput}
              value={document.kind}
            />
          )}

          <TextInput
            error={validationError ?? undefined}
            label={t("manual.fields.title", {
              locale: t(`manual.locales.${document.locale}`),
            })}
            onChange={(event) => {
              setValidationError(null);
              updateDocument({
                titles: {
                  ...document.titles,
                  [document.locale]: event.currentTarget.value,
                },
              });
            }}
            ref={titleInput}
            value={activeTitle}
          />
          <NumberInput
            label={t("manual.fields.year")}
            min={1800}
            max={3000}
            onChange={(value) =>
              updateDocument({ year: nullableNumber(value) })
            }
            value={document.year ?? ""}
          />
          <Textarea
            label={t("manual.fields.plot")}
            onChange={(event) =>
              updateDocument({ plot: event.currentTarget.value || null })
            }
            rows={3}
            value={document.plot ?? ""}
          />
          {showCollection ? (
            <Select
              clearable
              data={collections.map((collection) => ({
                label: collection.name,
                value: collection.id,
              }))}
              disabled={controlsDisabled}
              label={t("manual.fields.collection")}
              onChange={(value) => {
                if (disabled || reviewRef.current !== null) return;
                onCollectionIdChange(value);
              }}
              placeholder={t("manual.fields.noCollection")}
              value={collectionId}
            />
          ) : null}

          <UnstyledButton
            aria-controls={secondaryFieldsId}
            aria-expanded={secondaryFieldsOpen}
            disabled={controlsDisabled}
            onClick={() => setSecondaryFieldsOpen((open) => !open)}
            style={{
              ...wrappingButtonStyle,
              textAlign: "start",
              whiteSpace: "normal",
            }}
            type="button"
          >
            {t("manual.secondaryFields")}
          </UnstyledButton>
          <Collapse
            expanded={secondaryFieldsOpen}
            id={secondaryFieldsId}
            keepMounted
            keepMountedMode="display-none"
            transitionDuration={0}
          >
            <Stack gap="md">
              <TextInput
                label={t("manual.fields.originalTitle")}
                onChange={(event) =>
                  updateDocument({
                    original_title: event.currentTarget.value || null,
                  })
                }
                value={document.original_title ?? ""}
              />
              <TextInput
                label={t("manual.fields.releaseDate")}
                onChange={(event) =>
                  updateDocument({
                    release_date: event.currentTarget.value || null,
                  })
                }
                type="date"
                value={document.release_date ?? ""}
              />
              <NumberInput
                label={t("manual.fields.runtimeMinutes")}
                min={0}
                onChange={(value) =>
                  updateDocument({ runtime_minutes: nullableNumber(value) })
                }
                value={document.runtime_minutes ?? ""}
              />
              {(["genres", "tags", "countries", "studios"] as const).map(
                (field) => (
                  <TextInput
                    key={field}
                    label={t(`manual.fields.${field}`)}
                    onChange={(event) =>
                      disabled || reviewRef.current !== null
                        ? undefined
                        : onRawListsChange({
                            ...rawLists,
                            [field]: event.currentTarget.value,
                          })
                    }
                    value={rawLists[field]}
                  />
                ),
              )}
            </Stack>
          </Collapse>

          {document.kind === "series" ? (
            <Stack gap="md">
              <Text>
                {t("manual.hierarchySummary", {
                  episodes: episodeCount,
                  seasons: document.seasons.length,
                })}
              </Text>
              {document.seasons.map((season) => (
                <Fieldset
                  key={season.rowKey}
                  legend={t("manual.season.legend", { number: season.number })}
                >
                  <Stack gap="sm">
                    <NumberInput
                      label={t("manual.season.number")}
                      min={0}
                      onChange={(value) =>
                        updateSeason(season.rowKey, {
                          number:
                            typeof value === "number" ? value : season.number,
                        })
                      }
                      value={season.number}
                    />
                    <TextInput
                      label={t("manual.season.title")}
                      onChange={(event) =>
                        updateSeason(season.rowKey, {
                          title: event.currentTarget.value || null,
                        })
                      }
                      value={season.title ?? ""}
                    />
                    <Textarea
                      label={t("manual.season.plot")}
                      onChange={(event) =>
                        updateSeason(season.rowKey, {
                          plot: event.currentTarget.value || null,
                        })
                      }
                      rows={2}
                      value={season.plot ?? ""}
                    />

                    {season.episodes.map((episode) => (
                      <Fieldset
                        key={episode.rowKey}
                        legend={t("manual.episode.legend", {
                          number: episode.number,
                        })}
                      >
                        <Stack gap="xs">
                          <NumberInput
                            label={t("manual.episode.number")}
                            min={1}
                            onChange={(value) =>
                              updateEpisode(season.rowKey, episode.rowKey, {
                                number:
                                  typeof value === "number"
                                    ? value
                                    : episode.number,
                              })
                            }
                            value={episode.number}
                          />
                          <TextInput
                            label={t("manual.episode.title")}
                            onChange={(event) =>
                              updateEpisode(season.rowKey, episode.rowKey, {
                                title: event.currentTarget.value,
                              })
                            }
                            value={episode.title}
                          />
                          <Textarea
                            label={t("manual.episode.plot")}
                            onChange={(event) =>
                              updateEpisode(season.rowKey, episode.rowKey, {
                                plot: event.currentTarget.value || null,
                              })
                            }
                            rows={2}
                            value={episode.plot ?? ""}
                          />
                          <TextInput
                            label={t("manual.episode.airDate")}
                            onChange={(event) =>
                              updateEpisode(season.rowKey, episode.rowKey, {
                                air_date: event.currentTarget.value || null,
                              })
                            }
                            type="date"
                            value={episode.air_date ?? ""}
                          />
                          <NumberInput
                            label={t("manual.episode.runtimeMinutes")}
                            min={0}
                            onChange={(value) =>
                              updateEpisode(season.rowKey, episode.rowKey, {
                                runtime_minutes: nullableNumber(value),
                              })
                            }
                            value={episode.runtime_minutes ?? ""}
                          />
                          <NumberInput
                            label={t("manual.episode.ordering")}
                            onChange={(value) =>
                              updateEpisode(season.rowKey, episode.rowKey, {
                                ordering: nullableNumber(value),
                              })
                            }
                            value={episode.ordering ?? ""}
                          />
                          <Group justify="flex-end">
                            <Button
                              color="red"
                              onClick={(event) =>
                                requestEpisodeRemoval(season, episode, event)
                              }
                              style={wrappingButtonStyle}
                              styles={{ label: wrappingButtonLabelStyle }}
                              type="button"
                              variant="outline"
                            >
                              {t("manual.episode.remove", {
                                number: episode.number,
                              })}
                            </Button>
                          </Group>
                        </Stack>
                      </Fieldset>
                    ))}

                    <Group justify="space-between">
                      <Button
                        onClick={() => addEpisode(season)}
                        ref={(element) => {
                          if (element) {
                            addEpisodeButtons.current.set(
                              season.rowKey,
                              element,
                            );
                          } else {
                            addEpisodeButtons.current.delete(season.rowKey);
                          }
                        }}
                        type="button"
                      >
                        {t("manual.episode.add")}
                      </Button>
                      <Button
                        color="red"
                        onClick={(event) => requestSeasonRemoval(season, event)}
                        style={wrappingButtonStyle}
                        styles={{ label: wrappingButtonLabelStyle }}
                        type="button"
                        variant="outline"
                      >
                        {t("manual.season.remove", { number: season.number })}
                      </Button>
                    </Group>
                  </Stack>
                </Fieldset>
              ))}
              <Button
                onClick={addSeason}
                ref={addSeasonButton}
                type="button"
                variant="light"
              >
                {t("manual.season.add")}
              </Button>
            </Stack>
          ) : null}

          <Group justify="flex-end">
            <Button type="submit">{t("manual.save")}</Button>
          </Group>
        </Stack>
      </fieldset>
      <Modal
        closeOnClickOutside
        closeOnEscape
        opened={review !== null}
        onClose={cancelReview}
        onExitTransitionEnd={restoreReviewFocus}
        returnFocus={false}
        title={
          review?.kind === "episode"
            ? t("manual.destructive.removeEpisodeTitle", {
                number: review.episodeNumber,
              })
            : review?.kind === "season"
              ? t("manual.destructive.removeSeasonTitle", {
                  number: review.seasonNumber,
                })
              : review?.kind === "seriesToMovie"
                ? t("manual.destructive.changeSeriesToMovieTitle")
                : undefined
        }
        withCloseButton={false}
      >
        {review ? (
          <Stack>
            <Text>
              {review.kind === "episode"
                ? t("manual.destructive.removeEpisodeDescription")
                : review.kind === "season"
                  ? t("manual.destructive.removeSeasonDescription", {
                      count: review.descendantCount,
                      number: review.seasonNumber,
                    })
                  : t("manual.destructive.changeSeriesToMovieDescription", {
                      episodes: review.episodeCount,
                      seasons: review.seasonCount,
                    })}
            </Text>
            <Group justify="flex-end">
              <Button
                data-autofocus
                onClick={cancelReview}
                style={wrappingButtonStyle}
                styles={{ label: wrappingButtonLabelStyle }}
                variant="default"
              >
                {t("manual.destructive.cancel")}
              </Button>
              <Button
                color="red"
                onClick={confirmReview}
                style={wrappingButtonStyle}
                styles={{ label: wrappingButtonLabelStyle }}
              >
                {t("manual.destructive.confirm")}
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Modal>
    </Box>
  );
}
