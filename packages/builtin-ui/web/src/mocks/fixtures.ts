import type { components } from "../api/control.generated";

type Schema<Name extends keyof components["schemas"]> =
  components["schemas"][Name];

export type MockScenario =
  | "catalog"
  | "desktop"
  | "empty"
  | "error"
  | "loading"
  | "manual-confirmation"
  | "manual-csv-invalid"
  | "manual-expired"
  | "manual-invalid"
  | "mobile"
  | "ru"
  | "workflow";

export const sessions = {
  en: {
    csrf_token: "mock-csrf-en",
    metadata_locale: "en",
    supported_locales: ["en", "ru"],
    ui_locale: "en",
  },
  ru: {
    csrf_token: "mock-csrf-ru",
    metadata_locale: "ru",
    supported_locales: ["en", "ru"],
    ui_locale: "ru",
  },
} satisfies Record<"en" | "ru", Schema<"SessionView">>;

export const collections = [
  { id: "favorites", name: "Favorites", archived: false },
] satisfies Schema<"CollectionView">[];

export const catalogItems = [
  {
    archived: false,
    id: "arrival-2016",
    kind: "movie",
    latest_acquisition_status: "submitted",
    poster_url: null,
    provider_key: "tmdb",
    title: "Arrival",
    year: 2016,
  },
  {
    archived: false,
    id: "dark-2017",
    kind: "series",
    latest_acquisition_status: "pending",
    poster_url: null,
    provider_key: "tmdb",
    title: "Dark",
    year: 2017,
  },
] satisfies Schema<"CatalogItemView">[];

export const mediaDetail = {
  acquisitions: [],
  archived: false,
  collection_id: null,
  external_id: "329865",
  id: "arrival-2016",
  kind: "movie",
  metadata: {
    artwork: [],
    countries: ["US"],
    genres: ["Science Fiction"],
    kind: "movie",
    original_title: "Arrival",
    people: [],
    plot: "A linguist works with the military to communicate with alien lifeforms.",
    provider_ids: { tmdb: "329865" },
    ratings: [],
    release_date: "2016-11-11",
    runtime_minutes: 116,
    seasons: [],
    studios: [],
    tags: [],
    titles: {
      en: "Arrival",
      ru: "\u041f\u0440\u0438\u0431\u044b\u0442\u0438\u0435",
    },
    year: 2016,
  },
  provider_key: "tmdb",
} satisfies Schema<"MediaItemDetail">;

export const manualMovieDetail = {
  acquisitions: [],
  archived: false,
  collection_id: "favorites",
  external_id: "5ab363a4-6735-4a73-a2d8-8ca67acb7942",
  id: "manual-movie",
  kind: "movie",
  metadata: {
    artwork: [
      {
        kind: "poster",
        url: "https://images.example.invalid/manual-movie.jpg",
      },
    ],
    countries: ["CA"],
    genres: ["Drama"],
    kind: "movie",
    original_title: "A Manual Movie",
    people: [{ name: "Example Director", role: "director" }],
    plot: "A deterministic Manual movie fixture.",
    provider_ids: { imdb: "tt0000001" },
    ratings: [{ source: "fixture", value: 8.1, votes: 42 }],
    release_date: "2026-08-27",
    runtime_minutes: 101,
    seasons: [],
    studios: ["Fixture Studio"],
    tags: ["manual"],
    titles: {
      en: "Manual Movie",
      ru: "\u0420\u0443\u0447\u043d\u043e\u0439 \u0444\u0438\u043b\u044c\u043c",
    },
    year: 2026,
  },
  provider_key: "manual",
} satisfies Schema<"MediaItemDetail">;

export const manualSeriesDetail = {
  acquisitions: [],
  archived: false,
  collection_id: null,
  external_id: "e0a465bb-34eb-4565-bde2-b80d6e789b7c",
  id: "manual-series",
  kind: "series",
  metadata: {
    artwork: [],
    countries: ["DE"],
    genres: ["Mystery"],
    kind: "series",
    original_title: "A Manual Series",
    people: [
      { character: "The Archivist", name: "Example Actor", role: "cast" },
    ],
    plot: "A rich deterministic Manual series fixture.",
    provider_ids: { tvdb: "fixture-42" },
    ratings: [{ source: "fixture", value: 9.2 }],
    release_date: "2025-01-02",
    runtime_minutes: 48,
    seasons: [
      {
        episodes: [
          {
            air_date: "2025-01-01",
            number: 1,
            ordering: 1,
            plot: "The special begins.",
            runtime_minutes: 12,
            title: "Special",
          },
        ],
        number: 0,
        plot: "Special presentations.",
        title: "Specials",
      },
      {
        episodes: [
          {
            air_date: "2025-01-02",
            number: 1,
            ordering: 2,
            plot: "The story begins.",
            runtime_minutes: 48,
            title: "Pilot",
          },
        ],
        number: 1,
        plot: "The first season.",
        title: "Season One",
      },
    ],
    studios: ["Fixture Television"],
    tags: ["manual", "rich"],
    titles: {
      en: "Manual Series",
      ru: "\u0420\u0443\u0447\u043d\u043e\u0439 \u0441\u0435\u0440\u0438\u0430\u043b",
    },
    year: 2025,
  },
  provider_key: "manual",
} satisfies Schema<"MediaItemDetail">;

export const metadataProviders = [
  {
    attribution_key: "tmdb.attribution",
    capabilities: ["search", "select"],
    key: "tmdb",
    name_key: "tmdb.name",
    ready: true,
  },
  {
    attribution_key: "omdb.attribution",
    capabilities: ["search", "select"],
    key: "omdb",
    name_key: "omdb.name",
    ready: true,
  },
] satisfies Schema<"MetadataProviderView">[];

export const metadataResults = [
  {
    description:
      "A linguist works with the military to communicate with alien lifeforms.",
    external_id: "329865",
    kind: "movie",
    locale: "en",
    provider_key: "tmdb",
    poster_url: "https://images.example.invalid/posters/arrival.jpg",
    title: "Arrival",
    token: "metadata-token-tmdb",
    year: 2016,
  },
  {
    description: null,
    external_id: "tt2543164",
    kind: "movie",
    locale: "en",
    provider_key: "omdb",
    poster_url: null,
    title: "Arrival",
    token: "metadata-token-omdb",
    year: 2016,
  },
] satisfies Schema<"MetadataSearchResult">[];

export const releaseResults = [
  {
    indexer: "Example Indexer",
    seeders: 42,
    size: 8_000_000_000,
    title: "Arrival.2016.1080p.BluRay",
    token: "release-token-1",
  },
] satisfies Schema<"ReleaseSearchResult">[];

export const downloadDestinations = [
  { key: "movies", label: "Movies" },
  { key: "archive", label: "Archive" },
] satisfies Schema<"DownloadDestination">[];

export const acquisitions = {
  failed: {
    created_at: "2026-08-20T10:00:00Z",
    destination: "movies",
    error_code: "download_client_submission_failed",
    id: "acquisition-failed",
    media_item_id: "arrival-2016",
    release_title: "Arrival.2016.1080p.BluRay",
    status: "failed",
  },
  pending: {
    created_at: "2026-08-20T10:00:00Z",
    destination: "movies",
    error_code: null,
    id: "acquisition-pending",
    media_item_id: "arrival-2016",
    release_title: "Arrival.2016.1080p.BluRay",
    status: "pending",
  },
  submitted: {
    created_at: "2026-08-20T10:00:00Z",
    destination: "movies",
    error_code: null,
    id: "acquisition-submitted",
    media_item_id: "arrival-2016",
    release_title: "Arrival.2016.1080p.BluRay",
    status: "submitted",
  },
} satisfies Record<
  "failed" | "pending" | "submitted",
  Schema<"AcquisitionView">
>;

export const safeError = {
  error: { code: "metadata_unavailable", request_id: "mock-request-1" },
} satisfies Schema<"ControlErrorEnvelope">;

export const manualErrors = {
  confirmation: {
    error: {
      code: "confirmation_required",
      details: {
        confirmation_token: "manual-confirmation",
        kind: "manual",
      },
      request_id: "mock-manual-confirmation",
    },
  },
  csvInvalid: {
    error: {
      code: "episode_csv_invalid",
      request_id: "mock-episode-csv-invalid",
    },
  },
  expired: {
    error: {
      code: "selection_expired",
      request_id: "mock-manual-expired",
    },
  },
  invalid: {
    error: {
      code: "manual_import_invalid",
      request_id: "mock-manual-invalid",
    },
  },
} satisfies Record<
  "confirmation" | "csvInvalid" | "expired" | "invalid",
  Schema<"ControlErrorEnvelope">
>;
