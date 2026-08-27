import {
  Alert,
  Box,
  Button,
  Fieldset,
  Group,
  NumberInput,
  Select,
  Stack,
  Textarea,
  TextInput,
} from "@mantine/core";
import { type FormEvent, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { components } from "../api/control.generated";
import type {
  ManualEditorDocument,
  ManualEditorEpisode,
  ManualEditorSeason,
} from "./manual-document";

type Collection = components["schemas"]["CollectionView"];
type MediaKind = components["schemas"]["MediaKind"];

export interface ManualEditorProps {
  collectionId: string | null;
  collections: Collection[];
  document: ManualEditorDocument;
  onCollectionIdChange: (collectionId: string | null) => void;
  onDocumentChange: (document: ManualEditorDocument) => void;
  onSubmit: (
    document: ManualEditorDocument,
    collectionId: string | null,
  ) => void;
  showCollection?: boolean;
}

function nullableNumber(value: number | string): number | null {
  return typeof value === "number" ? value : null;
}

function commaSeparated(values: string[]): string {
  return values.join(", ");
}

function parseCommaSeparated(value: string): string[] {
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
}

function createRowKey(): string {
  return globalThis.crypto.randomUUID();
}

export function ManualEditor({
  collectionId,
  collections,
  document,
  onCollectionIdChange,
  onDocumentChange,
  onSubmit,
  showCollection = true,
}: ManualEditorProps) {
  const { t } = useTranslation();
  const titleInput = useRef<HTMLInputElement>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const activeTitle = document.titles[document.locale] ?? "";
  const identityLocked = document.external_id !== undefined;

  function updateDocument(update: Partial<ManualEditorDocument>) {
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
    updateDocument({
      kind,
      seasons: kind === "movie" ? [] : document.seasons,
    });
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeTitle.trim()) {
      setValidationError(t("manual.validation.titleRequired"));
      titleInput.current?.focus();
      return;
    }
    setValidationError(null);
    onSubmit(document, collectionId);
  }

  return (
    <Box
      component="form"
      data-testid="manual-editor-layout"
      onSubmit={submit}
      style={{ minWidth: 0, width: "100%" }}
    >
      <Stack gap="md">
        {validationError ? <Alert role="alert">{validationError}</Alert> : null}

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
            label={t("manual.fields.kind")}
            onChange={(value) => {
              if (value === "movie" || value === "series") selectKind(value);
            }}
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
        <TextInput
          label={t("manual.fields.originalTitle")}
          onChange={(event) =>
            updateDocument({
              original_title: event.currentTarget.value || null,
            })
          }
          value={document.original_title ?? ""}
        />
        <NumberInput
          label={t("manual.fields.year")}
          min={1800}
          max={3000}
          onChange={(value) => updateDocument({ year: nullableNumber(value) })}
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
        <TextInput
          label={t("manual.fields.releaseDate")}
          onChange={(event) =>
            updateDocument({ release_date: event.currentTarget.value || null })
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
        {(["genres", "tags", "countries", "studios"] as const).map((field) => (
          <TextInput
            key={field}
            label={t(`manual.fields.${field}`)}
            onChange={(event) =>
              updateDocument({
                [field]: parseCommaSeparated(event.currentTarget.value),
              })
            }
            value={commaSeparated(document[field])}
          />
        ))}
        {showCollection ? (
          <Select
            clearable
            data={collections.map((collection) => ({
              label: collection.name,
              value: collection.id,
            }))}
            label={t("manual.fields.collection")}
            onChange={onCollectionIdChange}
            placeholder={t("manual.fields.noCollection")}
            value={collectionId}
          />
        ) : null}

        {document.kind === "series" ? (
          <Stack gap="md">
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
                            onClick={() =>
                              updateSeason(season.rowKey, {
                                episodes: season.episodes.filter(
                                  (candidate) =>
                                    candidate.rowKey !== episode.rowKey,
                                ),
                              })
                            }
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
                    <Button onClick={() => addEpisode(season)} type="button">
                      {t("manual.episode.add")}
                    </Button>
                    <Button
                      color="red"
                      onClick={() =>
                        updateDocument({
                          seasons: document.seasons.filter(
                            (candidate) => candidate.rowKey !== season.rowKey,
                          ),
                        })
                      }
                      type="button"
                      variant="outline"
                    >
                      {t("manual.season.remove", { number: season.number })}
                    </Button>
                  </Group>
                </Stack>
              </Fieldset>
            ))}
            <Button onClick={addSeason} type="button" variant="light">
              {t("manual.season.add")}
            </Button>
          </Stack>
        ) : null}

        <Group justify="flex-end">
          <Button type="submit">{t("manual.save")}</Button>
        </Group>
      </Stack>
    </Box>
  );
}
