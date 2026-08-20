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
});
