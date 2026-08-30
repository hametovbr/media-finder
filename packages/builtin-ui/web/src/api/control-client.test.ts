import { HttpResponse, delay, http } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ControlFailure, createControlClient } from "./control-client";

const baseUrl = "http://localhost/api/control";
const session = {
  csrf_token: "csrf-test-token",
  metadata_locale: "en" as const,
  supported_locales: ["en", "ru"] as const,
  ui_locale: "en" as const,
};

const server = setupServer();

const manualDocument = {
  artwork: [],
  countries: ["CA"],
  genres: ["Science Fiction"],
  kind: "series" as const,
  locale: "en" as const,
  people: [],
  provider_ids: { imdb: "tt-test" },
  ratings: [],
  schema_version: "1" as const,
  seasons: [
    {
      episodes: [{ number: 1, title: "Special" }],
      number: 0,
      title: "Specials",
    },
  ],
  studios: ["Fixture Studio"],
  tags: ["fixture"],
  titles: {
    en: "Manual Series",
    ru: "\u0420\u0443\u0447\u043d\u043e\u0439 \u0441\u0435\u0440\u0438\u0430\u043b",
  },
};

const manualItem = {
  acquisitions: [],
  archived: false,
  collection_id: "collection-1",
  external_id: "e0a465bb-34eb-4565-bde2-b80d6e789b7c",
  id: "manual-item-1",
  kind: "series" as const,
  metadata: manualDocument,
  provider_key: "manual",
};

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

describe("ControlClient", () => {
  it("bootstraps the browser session through the control boundary without credentials", async () => {
    server.use(
      http.get(`${baseUrl}/v1/session`, ({ request }) => {
        expect(request.headers.has("authorization")).toBe(false);
        expect(request.url).not.toContain("/api/v1");
        return HttpResponse.json(session);
      }),
    );

    const client = createControlClient({ baseUrl });

    await expect(client.bootstrapSession()).resolves.toEqual(session);
  });

  it("keeps the CSRF token in memory and injects it into JSON mutations", async () => {
    server.use(
      http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(session)),
      http.patch(`${baseUrl}/v1/session`, async ({ request }) => {
        expect(request.headers.get("content-type")).toContain(
          "application/json",
        );
        expect(request.headers.get("x-csrf-token")).toBe(session.csrf_token);
        expect(request.headers.has("authorization")).toBe(false);
        expect(await request.json()).toEqual({ ui_locale: "ru" });
        return HttpResponse.json({ ...session, ui_locale: "ru" });
      }),
    );

    const client = createControlClient({ baseUrl });
    await client.bootstrapSession();

    await expect(
      client.updateSession({ ui_locale: "ru" }),
    ).resolves.toMatchObject({
      ui_locale: "ru",
    });
  });

  it("serializes optional Prowlarr indexer identifiers in release searches", async () => {
    const requests: unknown[] = [];
    server.use(
      http.post(
        `${baseUrl}/v1/media-items/:itemId/release-searches`,
        async ({ request }) => {
          requests.push(await request.json());
          return HttpResponse.json([]);
        },
      ),
    );
    const client = createControlClient({ baseUrl });

    await client.searchReleases("item-1", "Arrival", [7, 12]);
    await client.searchReleases("item-1", "Arrival");

    expect(requests).toEqual([
      { indexer_ids: [7, 12], query: "Arrival" },
      { indexer_ids: [], query: "Arrival" },
    ]);
  });

  it("forwards request cancellation", async () => {
    server.use(
      http.get(`${baseUrl}/v1/session`, async () => {
        await delay("infinite");
        return HttpResponse.json(session);
      }),
    );
    const controller = new AbortController();
    const client = createControlClient({ baseUrl });

    const request = client.bootstrapSession(controller.signal);
    controller.abort();

    await expect(request).rejects.toMatchObject({ name: "AbortError" });
  });

  it("maps only safe machine errors and request identifiers", async () => {
    server.use(
      http.get(`${baseUrl}/v1/session`, () =>
        HttpResponse.json(
          {
            error: {
              code: "session_invalid",
              details: {
                upstream_message: "secret upstream response",
                url: "https://user:password@example.invalid/private",
              },
              request_id: "request-123",
            },
          },
          { status: 403 },
        ),
      ),
    );
    const client = createControlClient({ baseUrl });

    const failure = await client
      .bootstrapSession()
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ControlFailure);
    expect(failure).toMatchObject({
      code: "session_invalid",
      requestId: "request-123",
      status: 403,
    });
    expect(JSON.stringify(failure)).not.toContain("secret upstream response");
    expect(JSON.stringify(failure)).not.toContain("password");
  });

  it("matches direct control metadata transitions and invariant machine errors", async () => {
    const savedItem = {
      acquisitions: [],
      archived: false,
      collection_id: null,
      external_id: "metadata-42",
      id: "item-42",
      kind: "movie" as const,
      metadata: { kind: "movie", titles: { en: "Metadata match" } },
      provider_key: "fixture",
    };
    server.use(
      http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(session)),
      http.post(`${baseUrl}/v1/metadata-selections/:token`, ({ params }) => {
        if (params.token === "expired") {
          return HttpResponse.json(
            { error: { code: "selection_expired", request_id: "parity-1" } },
            { status: 409 },
          );
        }
        return HttpResponse.json(savedItem);
      }),
    );
    const browserClient = createControlClient({ baseUrl });
    await browserClient.bootstrapSession();

    const browserResult = await browserClient.selectMetadata("selected", false);
    const directResult = await browserClient.api.POST(
      "/v1/metadata-selections/{token}",
      {
        body: { confirm_similarity: false },
        params: { path: { token: "selected" } },
      },
    );
    expect(browserResult).toEqual(directResult.data);

    const browserFailure = await browserClient
      .selectMetadata("expired", false)
      .catch((error: unknown) => error);
    const directFailure = await browserClient.api.POST(
      "/v1/metadata-selections/{token}",
      {
        body: { confirm_similarity: false },
        params: { path: { token: "expired" } },
      },
    );
    expect(browserFailure).toMatchObject({
      code: directFailure.error?.error.code,
      status: directFailure.response.status,
    });
  });

  it("exposes the returned similarity confirmation token and no unrelated details", async () => {
    server.use(
      http.post(`${baseUrl}/v1/metadata-selections/:token`, () =>
        HttpResponse.json(
          {
            error: {
              code: "confirmation_required",
              details: {
                confirmation_token: "similarity-confirmation-token",
                kind: "similarity",
                upstream_url: "https://user:password@example.invalid/private",
              },
              request_id: "similarity-request",
            },
          },
          { status: 409 },
        ),
      ),
    );
    const client = createControlClient({ baseUrl });

    const failure = await client
      .selectMetadata("consumed-search-token", false)
      .catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ControlFailure);
    expect(failure).toMatchObject({
      code: "confirmation_required",
      confirmationToken: "similarity-confirmation-token",
      requestId: "similarity-request",
      status: 409,
    });
    expect(JSON.stringify(failure)).not.toContain("upstream_url");
    expect(JSON.stringify(failure)).not.toContain("password");
  });

  it("submits every Manual mutation through the typed CSRF-protected control path", async () => {
    const requests: Array<{ body: unknown; method: string; url: string }> = [];
    server.use(
      http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(session)),
      http.post(`${baseUrl}/v1/manual-imports`, async ({ request }) => {
        requests.push({
          body: await request.json(),
          method: request.method,
          url: request.url,
        });
        expect(request.headers.get("content-type")).toContain(
          "application/json",
        );
        expect(request.headers.get("x-csrf-token")).toBe(session.csrf_token);
        expect(request.headers.has("authorization")).toBe(false);
        return HttpResponse.json(manualItem, { status: 201 });
      }),
      http.post(
        `${baseUrl}/v1/manual-imports/:token/confirm`,
        async ({ request }) => {
          requests.push({
            body: (await request.text()) || null,
            method: request.method,
            url: request.url,
          });
          expect(request.headers.get("x-csrf-token")).toBe(session.csrf_token);
          return HttpResponse.json(manualItem);
        },
      ),
      http.put(
        `${baseUrl}/v1/media-items/:itemId/manual-metadata`,
        async ({ request }) => {
          requests.push({
            body: await request.json(),
            method: request.method,
            url: request.url,
          });
          expect(request.headers.get("x-csrf-token")).toBe(session.csrf_token);
          return HttpResponse.json(manualItem);
        },
      ),
      http.post(
        `${baseUrl}/v1/media-items/:itemId/episode-imports`,
        async ({ request }) => {
          requests.push({
            body: await request.json(),
            method: request.method,
            url: request.url,
          });
          expect(request.headers.get("x-csrf-token")).toBe(session.csrf_token);
          return HttpResponse.json(manualItem);
        },
      ),
    );
    const client = createControlClient({ baseUrl });
    await client.bootstrapSession();

    await expect(
      client.importManual({
        collection_id: "collection-1",
        document: manualDocument,
      }),
    ).resolves.toEqual(manualItem);
    await expect(client.confirmManual("token/with space")).resolves.toEqual(
      manualItem,
    );
    await expect(
      client.editManual("item/with space", manualDocument),
    ).resolves.toEqual(manualItem);
    await expect(
      client.importEpisodes(
        "item/with space",
        "season,episode,title\n0,1,Special\n",
      ),
    ).resolves.toEqual(manualItem);

    expect(requests).toEqual([
      {
        body: { collection_id: "collection-1", document: manualDocument },
        method: "POST",
        url: `${baseUrl}/v1/manual-imports`,
      },
      {
        body: null,
        method: "POST",
        url: `${baseUrl}/v1/manual-imports/token%2Fwith%20space/confirm`,
      },
      {
        body: manualDocument,
        method: "PUT",
        url: `${baseUrl}/v1/media-items/item%2Fwith%20space/manual-metadata`,
      },
      {
        body: { csv: "season,episode,title\n0,1,Special\n" },
        method: "POST",
        url: `${baseUrl}/v1/media-items/item%2Fwith%20space/episode-imports`,
      },
    ]);
  });

  it("exposes only an allowlisted Manual confirmation token from error details", async () => {
    server.use(
      http.post(`${baseUrl}/v1/manual-imports`, async ({ request }) => {
        const body = (await request.json()) as {
          document?: { titles?: { en?: string } };
        };
        const title = body.document?.titles?.en;
        const detailsByTitle: Record<string, unknown> = {
          "Manual valid": {
            confirmation_token: "manual-confirmation-token",
            kind: "manual",
            upstream_url: "https://user:password@example.invalid/private",
          },
          "Manual wrong kind": {
            confirmation_token: "metadata-token",
            kind: "metadata",
          },
          "Manual malformed": {
            confirmation_token: { secret: "not-a-string" },
            kind: "manual",
          },
        };
        return HttpResponse.json(
          {
            error: {
              code: "confirmation_required",
              details: detailsByTitle[title ?? ""] ?? null,
              request_id: "manual-request",
            },
          },
          { status: 409 },
        );
      }),
    );
    const client = createControlClient({ baseUrl });
    const failureFor = async (title: string) =>
      client
        .importManual({
          document: {
            ...manualDocument,
            titles: { en: title },
          },
        })
        .catch((error: unknown) => error);

    const valid = await failureFor("Manual valid");
    const wrongKind = await failureFor("Manual wrong kind");
    const malformed = await failureFor("Manual malformed");

    expect(valid).toBeInstanceOf(ControlFailure);
    expect(valid).toMatchObject({
      code: "confirmation_required",
      confirmationToken: "manual-confirmation-token",
      requestId: "manual-request",
      status: 409,
    });
    expect(wrongKind).toMatchObject({ confirmationToken: null });
    expect(malformed).toMatchObject({ confirmationToken: null });
    expect(JSON.stringify(valid)).not.toContain("upstream_url");
    expect(JSON.stringify(valid)).not.toContain("password");
    expect(JSON.stringify(valid)).not.toContain("not-a-string");
  });
});
