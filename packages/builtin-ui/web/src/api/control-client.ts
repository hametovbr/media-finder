import createClient, {
  type Client,
  type ClientOptions,
  type Middleware,
} from "openapi-fetch";

import type { components, paths } from "./control.generated";

export const CONTROL_BASE_URL = "/api/control";

type Session = components["schemas"]["SessionView"];
type SessionUpdate = components["schemas"]["SessionUpdate"];
type CatalogPage = components["schemas"]["Page_CatalogItemView_"];
type CollectionPage = components["schemas"]["Page_CollectionView_"];
type MediaItemDetail = components["schemas"]["MediaItemDetail"];
type MetadataProvider = components["schemas"]["MetadataProviderView"];
type MetadataSearchResult = components["schemas"]["MetadataSearchResult"];
type ManualDocument = components["schemas"]["ManualDocumentV1"];
type ManualImportRequest = components["schemas"]["ManualImportRequest"];
type ReleaseSearchResult = components["schemas"]["ReleaseSearchResult"];
type DownloadDestination = components["schemas"]["DownloadDestination"];
type Acquisition = components["schemas"]["AcquisitionView"];

export interface CatalogRequest {
  collectionId?: string;
  cursor?: string;
  locale: components["schemas"]["Locale"];
  uncategorized?: boolean;
}

export class ControlFailure extends Error {
  readonly code: string;
  readonly confirmationToken: string | null;
  readonly requestId: string | null;
  readonly status: number;

  constructor(
    code: string,
    status: number,
    requestId: string | null = null,
    confirmationToken: string | null = null,
  ) {
    super(code);
    this.name = "ControlFailure";
    this.code = code;
    this.confirmationToken = confirmationToken;
    Object.defineProperty(this, "confirmationToken", { enumerable: false });
    this.requestId = requestId;
    this.status = status;
  }
}

export interface ControlClient {
  readonly api: Client<paths>;
  bootstrapSession(signal?: AbortSignal): Promise<Session>;
  getMediaItem(
    itemId: string,
    locale: components["schemas"]["Locale"],
    signal?: AbortSignal,
  ): Promise<MediaItemDetail>;
  importManual(
    request: ManualImportRequest,
    signal?: AbortSignal,
  ): Promise<MediaItemDetail>;
  confirmManual(token: string, signal?: AbortSignal): Promise<MediaItemDetail>;
  editManual(
    itemId: string,
    document: ManualDocument,
    signal?: AbortSignal,
  ): Promise<MediaItemDetail>;
  importEpisodes(
    itemId: string,
    csv: string,
    signal?: AbortSignal,
  ): Promise<MediaItemDetail>;
  listCatalog(
    request: CatalogRequest,
    signal?: AbortSignal,
  ): Promise<CatalogPage>;
  listCollections(signal?: AbortSignal): Promise<CollectionPage>;
  listMetadataProviders(signal?: AbortSignal): Promise<MetadataProvider[]>;
  searchMetadata(
    query: string,
    locale: components["schemas"]["Locale"],
    providerKeys?: string[],
    signal?: AbortSignal,
  ): Promise<MetadataSearchResult[]>;
  selectMetadata(
    token: string,
    confirmSimilarity: boolean,
    collectionId?: string,
    signal?: AbortSignal,
  ): Promise<MediaItemDetail>;
  searchReleases(
    itemId: string,
    query: string,
    indexerIds?: number[],
    signal?: AbortSignal,
  ): Promise<ReleaseSearchResult[]>;
  listDownloadDestinations(
    signal?: AbortSignal,
  ): Promise<DownloadDestination[]>;
  submitAcquisition(
    request: {
      destination: string;
      idempotencyKey: string;
      mediaItemId: string;
      releaseToken: string;
    },
    signal?: AbortSignal,
  ): Promise<Acquisition>;
  updateSession(update: SessionUpdate, signal?: AbortSignal): Promise<Session>;
}

interface ControlClientOptions {
  baseUrl?: string;
  fetch?: ClientOptions["fetch"];
}

function normalizeFailure(error: unknown, response: Response): ControlFailure {
  if (typeof error === "object" && error !== null && "error" in error) {
    const envelope = error as {
      error?: { code?: unknown; details?: unknown; request_id?: unknown };
    };
    const code = envelope.error?.code;
    const requestId = envelope.error?.request_id;
    if (typeof code === "string") {
      const details = envelope.error?.details;
      const confirmationToken =
        code === "confirmation_required" &&
        typeof details === "object" &&
        details !== null &&
        "kind" in details &&
        details.kind === "manual" &&
        "confirmation_token" in details &&
        typeof details.confirmation_token === "string"
          ? details.confirmation_token
          : null;
      return new ControlFailure(
        code,
        response.status,
        typeof requestId === "string" ? requestId : null,
        confirmationToken,
      );
    }
  }

  return new ControlFailure("unexpected_response", response.status);
}

export function createControlClient(
  options: ControlClientOptions = {},
): ControlClient {
  let csrfToken: string | undefined;
  const api = createClient<paths>({
    baseUrl: options.baseUrl ?? CONTROL_BASE_URL,
    credentials: "same-origin",
    fetch: options.fetch,
  });
  const securityMiddleware: Middleware = {
    onRequest({ request }) {
      request.headers.delete("Authorization");
      if (!new Set(["GET", "HEAD", "OPTIONS"]).has(request.method)) {
        request.headers.set("Content-Type", "application/json");
        if (csrfToken !== undefined) {
          request.headers.set("X-CSRF-Token", csrfToken);
        }
      }
    },
  };
  api.use(securityMiddleware);

  async function bootstrapSession(signal?: AbortSignal): Promise<Session> {
    const { data, error, response } = await api.GET("/v1/session", { signal });
    if (data === undefined) {
      throw normalizeFailure(error, response);
    }
    csrfToken = data.csrf_token;
    return data;
  }

  async function updateSession(
    update: SessionUpdate,
    signal?: AbortSignal,
  ): Promise<Session> {
    const { data, error, response } = await api.PATCH("/v1/session", {
      body: update,
      signal,
    });
    if (data === undefined) {
      throw normalizeFailure(error, response);
    }
    csrfToken = data.csrf_token;
    return data;
  }

  async function listCollections(
    signal?: AbortSignal,
  ): Promise<CollectionPage> {
    const { data, error, response } = await api.GET("/v1/collections", {
      params: { query: { archived: false, limit: 100 } },
      signal,
    });
    if (data === undefined) {
      throw normalizeFailure(error, response);
    }
    return data;
  }

  async function listCatalog(
    request: CatalogRequest,
    signal?: AbortSignal,
  ): Promise<CatalogPage> {
    const { data, error, response } = await api.GET("/v1/media-items", {
      params: {
        query: {
          archived: false,
          collection_id: request.collectionId,
          cursor: request.cursor,
          limit: 50,
          locale: request.locale,
          uncategorized: request.uncategorized ?? false,
        },
      },
      signal,
    });
    if (data === undefined) {
      throw normalizeFailure(error, response);
    }
    return data;
  }

  async function getMediaItem(
    itemId: string,
    locale: components["schemas"]["Locale"],
    signal?: AbortSignal,
  ): Promise<MediaItemDetail> {
    const { data, error, response } = await api.GET(
      "/v1/media-items/{item_id}",
      {
        params: { path: { item_id: itemId }, query: { locale } },
        signal,
      },
    );
    if (data === undefined) {
      throw normalizeFailure(error, response);
    }
    return data;
  }

  async function listMetadataProviders(
    signal?: AbortSignal,
  ): Promise<MetadataProvider[]> {
    const { data, error, response } = await api.GET("/v1/metadata-providers", {
      signal,
    });
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  async function importManual(
    request: ManualImportRequest,
    signal?: AbortSignal,
  ): Promise<MediaItemDetail> {
    const { data, error, response } = await api.POST("/v1/manual-imports", {
      body: request,
      signal,
    });
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  async function confirmManual(
    token: string,
    signal?: AbortSignal,
  ): Promise<MediaItemDetail> {
    const { data, error, response } = await api.POST(
      "/v1/manual-imports/{token}/confirm",
      {
        params: { path: { token } },
        signal,
      },
    );
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  async function editManual(
    itemId: string,
    document: ManualDocument,
    signal?: AbortSignal,
  ): Promise<MediaItemDetail> {
    const { data, error, response } = await api.PUT(
      "/v1/media-items/{item_id}/manual-metadata",
      {
        body: document,
        params: { path: { item_id: itemId } },
        signal,
      },
    );
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  async function importEpisodes(
    itemId: string,
    csv: string,
    signal?: AbortSignal,
  ): Promise<MediaItemDetail> {
    const { data, error, response } = await api.POST(
      "/v1/media-items/{item_id}/episode-imports",
      {
        body: { csv },
        params: { path: { item_id: itemId } },
        signal,
      },
    );
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  async function searchMetadata(
    query: string,
    locale: components["schemas"]["Locale"],
    providerKeys: string[] = [],
    signal?: AbortSignal,
  ): Promise<MetadataSearchResult[]> {
    const { data, error, response } = await api.POST("/v1/metadata-searches", {
      body: { locale, provider_keys: providerKeys, query },
      signal,
    });
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  async function selectMetadata(
    token: string,
    confirmSimilarity: boolean,
    collectionId?: string,
    signal?: AbortSignal,
  ): Promise<MediaItemDetail> {
    const { data, error, response } = await api.POST(
      "/v1/metadata-selections/{token}",
      {
        body: {
          collection_id: collectionId,
          confirm_similarity: confirmSimilarity,
        },
        params: { path: { token } },
        signal,
      },
    );
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  async function searchReleases(
    itemId: string,
    query: string,
    indexerIds: number[] = [],
    signal?: AbortSignal,
  ): Promise<ReleaseSearchResult[]> {
    const { data, error, response } = await api.POST(
      "/v1/media-items/{item_id}/release-searches",
      {
        body: { indexer_ids: indexerIds, query },
        params: { path: { item_id: itemId } },
        signal,
      },
    );
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  async function listDownloadDestinations(
    signal?: AbortSignal,
  ): Promise<DownloadDestination[]> {
    const { data, error, response } = await api.GET(
      "/v1/download-destinations",
      { signal },
    );
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  async function submitAcquisition(
    request: {
      destination: string;
      idempotencyKey: string;
      mediaItemId: string;
      releaseToken: string;
    },
    signal?: AbortSignal,
  ): Promise<Acquisition> {
    const { data, error, response } = await api.POST("/v1/acquisitions", {
      body: {
        destination: request.destination,
        idempotency_key: request.idempotencyKey,
        media_item_id: request.mediaItemId,
        release_token: request.releaseToken,
      },
      signal,
    });
    if (data === undefined) throw normalizeFailure(error, response);
    return data;
  }

  return {
    api,
    bootstrapSession,
    confirmManual,
    editManual,
    getMediaItem,
    importEpisodes,
    importManual,
    listCatalog,
    listCollections,
    listMetadataProviders,
    listDownloadDestinations,
    searchMetadata,
    searchReleases,
    selectMetadata,
    submitAcquisition,
    updateSession,
  };
}
