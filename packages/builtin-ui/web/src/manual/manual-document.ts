import type { components } from "../api/control.generated";

type EpisodeDocument = components["schemas"]["EpisodeDocument"];
type Locale = components["schemas"]["Locale"];
type ManualDocument = components["schemas"]["ManualDocumentV1"];
type MediaItemDetail = components["schemas"]["MediaItemDetail"];
type MediaKind = components["schemas"]["MediaKind"];
type SeasonDocument = components["schemas"]["SeasonDocument"];

export type ManualEditorEpisode = EpisodeDocument & { rowKey: string };
export type ManualEditorSeason = Omit<SeasonDocument, "episodes"> & {
  episodes: ManualEditorEpisode[];
  rowKey: string;
};
export type ManualEditorDocument = Omit<ManualDocument, "seasons"> & {
  seasons: ManualEditorSeason[];
};

export const MANUAL_LIST_FIELDS = [
  "genres",
  "tags",
  "countries",
  "studios",
] as const;

export type ManualRawLists = Record<
  (typeof MANUAL_LIST_FIELDS)[number],
  string
>;

export function createManualDocument(
  kind: MediaKind,
  locale: Locale,
): ManualDocument {
  return {
    artwork: [],
    countries: [],
    genres: [],
    kind,
    locale,
    original_title: null,
    people: [],
    plot: null,
    provider_ids: {},
    ratings: [],
    release_date: null,
    runtime_minutes: null,
    schema_version: "1",
    seasons: [],
    studios: [],
    tags: [],
    titles: { [locale]: "" },
    year: null,
  };
}

export function manualDocumentFromItem(
  item: MediaItemDetail,
  locale: Locale,
): ManualDocument {
  return {
    ...structuredClone(item.metadata),
    external_id: item.external_id,
    kind: item.kind,
    locale,
    schema_version: "1",
  };
}

export function withManualRowKeys(
  document: ManualDocument,
  createRowKey: () => string,
): ManualEditorDocument {
  return {
    ...structuredClone(document),
    seasons: document.seasons.map((season) => ({
      ...structuredClone(season),
      episodes: season.episodes.map((episode) => ({
        ...structuredClone(episode),
        rowKey: createRowKey(),
      })),
      rowKey: createRowKey(),
    })),
  };
}

export function toManualDocument(
  editorDocument: ManualEditorDocument,
): ManualDocument {
  return {
    ...editorDocument,
    seasons: editorDocument.seasons.map((editorSeason) => {
      const { rowKey, ...season } = editorSeason;
      void rowKey;
      return {
        ...season,
        episodes: editorSeason.episodes.map((editorEpisode) => {
          const { rowKey: episodeRowKey, ...episode } = editorEpisode;
          void episodeRowKey;
          return episode;
        }),
      };
    }),
  };
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

export function createManualRawLists(
  document: ManualEditorDocument,
): ManualRawLists {
  return {
    countries: commaSeparated(document.countries),
    genres: commaSeparated(document.genres),
    studios: commaSeparated(document.studios),
    tags: commaSeparated(document.tags),
  };
}

export function projectManualDocument(
  editorDocument: ManualEditorDocument,
  initialRawLists: ManualRawLists,
  rawLists: ManualRawLists,
): ManualDocument {
  const document = toManualDocument(editorDocument);
  for (const field of MANUAL_LIST_FIELDS) {
    if (rawLists[field] !== initialRawLists[field]) {
      document[field] = parseCommaSeparated(rawLists[field]);
    }
  }
  return document;
}

export function manualDraftEquals(
  initialDocument: ManualEditorDocument,
  document: ManualEditorDocument,
  initialRawLists: ManualRawLists,
  rawLists: ManualRawLists,
  initialCollectionId: string | null,
  collectionId: string | null,
): boolean {
  return (
    JSON.stringify(toManualDocument(initialDocument)) ===
      JSON.stringify(toManualDocument(document)) &&
    MANUAL_LIST_FIELDS.every(
      (field) => initialRawLists[field] === rawLists[field],
    ) &&
    initialCollectionId === collectionId
  );
}
