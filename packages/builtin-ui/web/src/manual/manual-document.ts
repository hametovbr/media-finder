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
