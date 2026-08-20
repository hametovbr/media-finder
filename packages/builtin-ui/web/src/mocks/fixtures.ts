import type { components } from "../api/control.generated";

type Schema<Name extends keyof components["schemas"]> =
  components["schemas"][Name];

export type MockScenario =
  | "catalog"
  | "desktop"
  | "empty"
  | "error"
  | "loading"
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
    external_id: "329865",
    kind: "movie",
    locale: "en",
    provider_key: "tmdb",
    title: "Arrival",
    token: "metadata-token-tmdb",
    year: 2016,
  },
  {
    external_id: "tt2543164",
    kind: "movie",
    locale: "en",
    provider_key: "omdb",
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
