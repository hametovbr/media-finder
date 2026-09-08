import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { createControlClient } from "../api/control-client";
import { ControlProvider } from "../api/control-provider";
import { appRoutes } from "../app-router";
import { createUiI18n } from "../i18n";
import {
  mediaDetail,
  metadataProviders,
  metadataResults,
  sessions,
} from "../mocks/fixtures";

const baseUrl = "http://localhost/api/control";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPage({ strict = false }: { strict?: boolean } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(appRoutes, { initialEntries: ["/add"] });
  const page = (
    <I18nextProvider i18n={createUiI18n("en")}>
      <QueryClientProvider client={queryClient}>
        <MantineProvider>
          <ControlProvider client={createControlClient({ baseUrl })}>
            <RouterProvider router={router} />
          </ControlProvider>
        </MantineProvider>
      </QueryClientProvider>
    </I18nextProvider>
  );
  return {
    router,
    ...render(strict ? <StrictMode>{page}</StrictMode> : page),
  };
}

function useBaseHandlers() {
  server.use(
    http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
    http.get(`${baseUrl}/v1/metadata-providers`, () =>
      HttpResponse.json(metadataProviders),
    ),
    http.post(`${baseUrl}/v1/metadata-searches`, async ({ request }) => {
      expect(await request.json()).toEqual({
        locale: "en",
        provider_keys: [],
        query: "Arrival",
      });
      return HttpResponse.json(metadataResults);
    }),
  );
}

async function reachResults(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", {
      name: "Search metadata providers",
    }),
  );
  await user.type(
    await screen.findByRole("searchbox", { name: "Title" }),
    "Arrival",
  );
  await user.click(screen.getByRole("button", { name: "Search" }));
  return screen.findByRole("group", { name: "tmdb" });
}

describe("MetadataPage", () => {
  it("shows a retry and Manual alternative when provider discovery fails", async () => {
    server.use(
      http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
      http.get(`${baseUrl}/v1/metadata-providers`, () =>
        HttpResponse.json(
          { error: { code: "metadata_provider_unavailable" } },
          { status: 503 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
    expect(
      screen.getByRole("link", { name: "Enter or import Manual metadata" }),
    ).toBeVisible();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });

  it("keeps the provider recovery action focused while its retry is pending", async () => {
    let resolveRetry: () => void = () => undefined;
    const retryGate = new Promise<void>((resolve) => {
      resolveRetry = resolve;
    });
    let attempts = 0;
    server.use(
      http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
      http.get(`${baseUrl}/v1/metadata-providers`, async () => {
        attempts += 1;
        if (attempts === 1)
          return HttpResponse.json(
            { error: { code: "metadata_provider_unavailable" } },
            { status: 503 },
          );
        await retryGate;
        return HttpResponse.json(metadataProviders);
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    const retry = await screen.findByRole("button", { name: "Retry" });
    retry.focus();
    await user.keyboard("{Enter}");

    expect(retry).toHaveFocus();
    expect(retry).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("alert")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Retrying request");
    resolveRetry();
    const input = await screen.findByRole("searchbox", { name: "Title" });
    expect(input).toHaveFocus();
  });

  it("renders a status and Manual alternative while providers load", async () => {
    let resolveProviders: () => void = () => undefined;
    const providersGate = new Promise<void>((resolve) => {
      resolveProviders = resolve;
    });
    server.use(
      http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
      http.get(`${baseUrl}/v1/metadata-providers`, async () => {
        await providersGate;
        return HttpResponse.json(metadataProviders);
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Loading metadata providers",
    );
    expect(
      screen.getByRole("link", { name: "Enter or import Manual metadata" }),
    ).toBeVisible();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    resolveProviders();
  });

  it("offers Manual metadata without a provider search when discovery is empty", async () => {
    server.use(
      http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
      http.get(`${baseUrl}/v1/metadata-providers`, () =>
        HttpResponse.json([
          { ...metadataProviders[0], capabilities: [], ready: false },
        ]),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "No metadata providers are available.",
    );
    expect(
      screen.getByRole("link", { name: "Enter or import Manual metadata" }),
    ).toBeVisible();
    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
  });

  it("retries a failed search with its submitted query after the field is edited", async () => {
    useBaseHandlers();
    let attempts = 0;
    server.use(
      http.post(`${baseUrl}/v1/metadata-searches`, async ({ request }) => {
        const body = (await request.json()) as { query: string };
        attempts += 1;
        if (attempts === 1)
          return HttpResponse.json(
            { error: { code: "unexpected_response" } },
            { status: 500 },
          );
        expect(body.query).toBe("Arrival");
        return HttpResponse.json(metadataResults);
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    const input = await screen.findByRole("searchbox", { name: "Title" });
    await user.type(input, "Arrival");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    await user.clear(input);
    await user.type(input, "Alien");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("group", { name: "tmdb" })).toBeVisible();
    expect(attempts).toBe(2);
  });

  it("identifies the submitted query when a search fails", async () => {
    useBaseHandlers();
    server.use(
      http.post(`${baseUrl}/v1/metadata-searches`, () =>
        HttpResponse.json(
          { error: { code: "unexpected_response" } },
          { status: 500 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    await user.type(
      await screen.findByRole("searchbox", { name: "Title" }),
      "Arrival",
    );
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Search failed for “Arrival”",
    );
  });

  it("returns focus to the title after a focused search retry succeeds", async () => {
    useBaseHandlers();
    let attempts = 0;
    let resolveRetry: () => void = () => undefined;
    const retryGate = new Promise<void>((resolve) => {
      resolveRetry = resolve;
    });
    server.use(
      http.post(`${baseUrl}/v1/metadata-searches`, async () => {
        attempts += 1;
        if (attempts === 1)
          return HttpResponse.json(
            { error: { code: "unexpected_response" } },
            { status: 500 },
          );
        await retryGate;
        return HttpResponse.json(metadataResults);
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    const input = await screen.findByRole("searchbox", { name: "Title" });
    await user.type(input, "Arrival");
    await user.click(screen.getByRole("button", { name: "Search" }));
    const retry = await screen.findByRole("button", { name: "Retry" });
    retry.focus();
    await user.keyboard("{Enter}");
    resolveRetry();

    expect(await screen.findByRole("group", { name: "tmdb" })).toBeVisible();
    expect(input).toHaveFocus();
  });

  it("keeps an edited title focused when a search retry succeeds", async () => {
    useBaseHandlers();
    let attempts = 0;
    let resolveRetry: () => void = () => undefined;
    const retryGate = new Promise<void>((resolve) => {
      resolveRetry = resolve;
    });
    server.use(
      http.post(`${baseUrl}/v1/metadata-searches`, async () => {
        attempts += 1;
        if (attempts === 1)
          return HttpResponse.json(
            { error: { code: "unexpected_response" } },
            { status: 500 },
          );
        await retryGate;
        return HttpResponse.json(metadataResults);
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    const input = await screen.findByRole("searchbox", { name: "Title" });
    await user.type(input, "Arrival");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.click(await screen.findByRole("button", { name: "Retry" }));
    await user.clear(input);
    await user.type(input, "Alien");
    resolveRetry();

    expect(await screen.findByRole("group", { name: "tmdb" })).toBeVisible();
    expect(input).toHaveFocus();
    expect(input).toHaveValue("Alien");
  });

  it("distinguishes the initial state from an empty successful search", async () => {
    useBaseHandlers();
    server.use(
      http.post(`${baseUrl}/v1/metadata-searches`, () => HttpResponse.json([])),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await user.type(
      await screen.findByRole("searchbox", { name: "Title" }),
      "Arrival",
    );
    await user.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "No results for “Arrival”",
    );
  });

  it("starts one metadata search for repeated same-tick form activation", async () => {
    useBaseHandlers();
    let requests = 0;
    let resolveSearch: () => void = () => undefined;
    const searchGate = new Promise<void>((resolve) => {
      resolveSearch = resolve;
    });
    server.use(
      http.post(`${baseUrl}/v1/metadata-searches`, async () => {
        requests += 1;
        await searchGate;
        return HttpResponse.json(metadataResults);
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    const input = await screen.findByRole("searchbox", { name: "Title" });
    await user.type(input, "Arrival");
    const form = input.closest("form");
    if (form === null) throw new Error("metadata_search_form_missing");
    fireEvent.submit(form);
    fireEvent.submit(form);

    await waitFor(() => expect(requests).toBe(1));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Searching for “Arrival”",
    );
    resolveSearch();
    expect(await screen.findByRole("group", { name: "tmdb" })).toBeVisible();
  });

  it("does not restore an abandoned search after StrictMode navigation", async () => {
    useBaseHandlers();
    let resolveSearch: () => void = () => undefined;
    const searchGate = new Promise<void>((resolve) => {
      resolveSearch = resolve;
    });
    let requests = 0;
    server.use(
      http.post(`${baseUrl}/v1/metadata-searches`, async () => {
        requests += 1;
        await searchGate;
        return HttpResponse.json(metadataResults);
      }),
    );
    const user = userEvent.setup();
    const { router } = renderPage({ strict: true });
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    await user.type(
      await screen.findByRole("searchbox", { name: "Title" }),
      "Arrival",
    );
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() => expect(requests).toBe(1));

    await router.navigate("/add/manual");
    expect(
      await screen.findByRole("heading", { name: "Manual metadata" }),
    ).toBeVisible();
    resolveSearch();
    await router.navigate("/add");

    expect(
      await screen.findByRole("heading", { name: "Add title" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("group", { name: "tmdb" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("clears prior results immediately when a replacement search fails", async () => {
    useBaseHandlers();
    let attempts = 0;
    server.use(
      http.post(`${baseUrl}/v1/metadata-searches`, async () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json(metadataResults)
          : HttpResponse.json(
              { error: { code: "unexpected_response" } },
              { status: 500 },
            );
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "Search metadata providers" }),
    );
    const input = await screen.findByRole("searchbox", { name: "Title" });
    await user.type(input, "Arrival");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("group", { name: "tmdb" })).toBeVisible();
    await user.clear(input);
    await user.type(input, "Alien");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(
      screen.queryByRole("group", { name: "tmdb" }),
    ).not.toBeInTheDocument();
  });

  it("blocks search while metadata selection is pending", async () => {
    useBaseHandlers();
    let releaseSelection: () => void = () => undefined;
    const selectionGate = new Promise<void>((resolve) => {
      releaseSelection = resolve;
    });
    let searches = 0;
    server.use(
      http.post(`${baseUrl}/v1/metadata-selections/:token`, async () => {
        await selectionGate;
        return HttpResponse.json(mediaDetail, { status: 201 });
      }),
      http.post(`${baseUrl}/v1/metadata-searches`, async ({ request }) => {
        searches += 1;
        await request.json();
        return HttpResponse.json(metadataResults);
      }),
    );
    const user = userEvent.setup();
    renderPage();
    const tmdb = await reachResults(user);
    const input = screen.getByRole("searchbox", { name: "Title" });
    await user.click(within(tmdb).getByRole("button", { name: "Select" }));
    await user.clear(input);
    await user.type(input, "Alien");
    await user.click(screen.getByRole("button", { name: "Search" }));
    expect(searches).toBe(1);
    releaseSelection();
    expect(await screen.findByText("Saved to catalog")).toBeVisible();
  });

  it("renders grouped preview rows and selects directly from the initiating row", async () => {
    useBaseHandlers();
    let selectionBody: unknown;
    server.use(
      http.post(
        `${baseUrl}/v1/metadata-selections/:token`,
        async ({ params, request }) => {
          expect(params.token).toBe("metadata-token-tmdb");
          selectionBody = await request.json();
          return HttpResponse.json(mediaDetail, { status: 201 });
        },
      ),
    );
    const user = userEvent.setup();
    renderPage();

    const tmdb = await reachResults(user);
    const tmdbRow = within(tmdb).getByRole("article", { name: /Arrival/ });
    expect(within(tmdbRow).getByText("Arrival")).toBeVisible();
    expect(
      within(tmdbRow).getByText(
        "A linguist works with the military to communicate with alien lifeforms.",
      ),
    ).toBeVisible();
    const poster = within(tmdbRow).getByRole("img");
    expect(poster).toHaveAttribute(
      "src",
      "https://images.example.invalid/posters/arrival.jpg",
    );
    expect(poster).toHaveAttribute("loading", "lazy");
    expect(poster).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(
      within(screen.getByRole("group", { name: "omdb" })).getByText(/Arrival/),
    ).toBeVisible();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save to catalog" }),
    ).not.toBeInTheDocument();

    await user.click(within(tmdbRow).getByRole("button", { name: "Select" }));

    expect(selectionBody).toEqual({ confirm_similarity: false });
    expect(await screen.findByText("Saved to catalog")).toBeVisible();
    expect(screen.getByRole("link", { name: "Find release" })).toHaveAttribute(
      "href",
      `/items/${mediaDetail.id}/releases`,
    );
  });

  it("renders descriptions as plain text and uses a stable local poster fallback", async () => {
    useBaseHandlers();
    server.use(
      http.post(`${baseUrl}/v1/metadata-searches`, () =>
        HttpResponse.json([
          {
            ...metadataResults[0],
            description: "<strong>Plain provider text</strong>",
            poster_url: "https://images.example.invalid/posters/fails.jpg",
          },
          { ...metadataResults[1], description: null, poster_url: null },
        ]),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    const tmdb = await reachResults(user);
    const tmdbRow = within(tmdb).getByRole("article", { name: /Arrival/ });
    const description = within(tmdbRow).getByText(
      "<strong>Plain provider text</strong>",
    );
    expect(description.querySelector("strong")).toBeNull();
    fireEvent.error(within(tmdbRow).getByRole("img"));
    expect(
      within(tmdbRow).getByRole("img", {
        name: "Poster unavailable for Arrival",
      }),
    ).toHaveAttribute("data-poster-fallback", "true");

    const omdbRow = within(
      screen.getByRole("group", { name: "omdb" }),
    ).getByRole("article", { name: /Arrival/ });
    expect(within(omdbRow).queryByText(/Plain provider text/)).toBeNull();
    expect(
      within(omdbRow).getByRole("img", {
        name: "Poster unavailable for Arrival",
      }),
    ).toHaveAttribute("data-poster-fallback", "true");
    expect(
      within(omdbRow).getByRole("button", { name: "Select" }),
    ).toBeEnabled();
  });

  it("treats an exact duplicate response as the existing saved outcome", async () => {
    useBaseHandlers();
    server.use(
      http.post(`${baseUrl}/v1/metadata-selections/:token`, ({ params }) => {
        expect(params.token).toBe("metadata-token-omdb");
        return HttpResponse.json(mediaDetail, { status: 200 });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await reachResults(user);
    const omdbRow = within(
      screen.getByRole("group", { name: "omdb" }),
    ).getByRole("article", { name: /Arrival/ });

    await user.click(within(omdbRow).getByRole("button", { name: "Select" }));

    expect(await screen.findByText("Saved to catalog")).toBeVisible();
  });

  it("announces a recoverable row error and re-enables every selection action", async () => {
    useBaseHandlers();
    let attempts = 0;
    server.use(
      http.post(`${baseUrl}/v1/metadata-selections/:token`, () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json(
              { error: { code: "metadata_provider_unavailable" } },
              { status: 503 },
            )
          : HttpResponse.json(mediaDetail, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    const tmdb = await reachResults(user);
    const tmdbRow = within(tmdb).getByRole("article", { name: /Arrival/ });

    await user.click(within(tmdbRow).getByRole("button", { name: "Select" }));

    expect(await within(tmdbRow).findByRole("alert")).toHaveTextContent(
      "The server returned an unexpected response.",
    );
    for (const action of screen.getAllByRole("button", { name: "Select" })) {
      expect(action).toBeEnabled();
    }
    await user.click(within(tmdbRow).getByRole("button", { name: "Select" }));
    expect(await screen.findByText("Saved to catalog")).toBeVisible();
    expect(attempts).toBe(2);
  });

  it("keeps selection globally single-flight across rapid and cross-row activation", async () => {
    useBaseHandlers();
    let requestCount = 0;
    let releaseResponse: () => void = () => undefined;
    const responseGate = new Promise<void>((resolve) => {
      releaseResponse = resolve;
    });
    server.use(
      http.post(`${baseUrl}/v1/metadata-selections/:token`, async () => {
        requestCount += 1;
        await responseGate;
        return HttpResponse.json(mediaDetail, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    const tmdb = await reachResults(user);
    const tmdbAction = within(
      within(tmdb).getByRole("article", { name: /Arrival/ }),
    ).getByRole("button", { name: "Select" });
    const omdbAction = within(
      within(screen.getByRole("group", { name: "omdb" })).getByRole("article", {
        name: /Arrival/,
      }),
    ).getByRole("button", { name: "Select" });

    fireEvent.click(tmdbAction);
    fireEvent.click(tmdbAction);
    fireEvent.click(omdbAction);

    await waitFor(() => expect(requestCount).toBe(1));
    expect(
      within(tmdb).getByRole("status", { name: "Selecting Arrival" }),
    ).toBeVisible();
    expect(tmdbAction).toBeDisabled();
    expect(omdbAction).toBeDisabled();
    releaseResponse();
    expect(await screen.findByText("Saved to catalog")).toBeVisible();
    expect(requestCount).toBe(1);
  });

  it("confirms similarity once with the returned token and reaches the saved outcome", async () => {
    useBaseHandlers();
    const requests: Array<{ confirmSimilarity: boolean; token: string }> = [];
    server.use(
      http.post(
        `${baseUrl}/v1/metadata-selections/:token`,
        async ({ params, request }) => {
          const body = (await request.json()) as {
            confirm_similarity?: boolean;
          };
          requests.push({
            confirmSimilarity: body.confirm_similarity ?? false,
            token: String(params.token),
          });
          if (params.token === "metadata-token-tmdb") {
            return HttpResponse.json(
              {
                error: {
                  code: "confirmation_required",
                  details: {
                    confirmation_token: "metadata-confirmation-token",
                    kind: "similarity",
                  },
                  request_id: "confirm-1",
                },
              },
              { status: 409 },
            );
          }
          expect(params.token).toBe("metadata-confirmation-token");
          expect(body.confirm_similarity).toBe(true);
          return HttpResponse.json(mediaDetail);
        },
      ),
    );
    const user = userEvent.setup();
    renderPage();
    const tmdb = await reachResults(user);
    await user.click(
      within(within(tmdb).getByRole("article", { name: /Arrival/ })).getByRole(
        "button",
        { name: "Select" },
      ),
    );

    const confirmation = await screen.findByRole("dialog", {
      name: "Confirm similar title",
    });
    await waitFor(() => expect(confirmation).toBeVisible());
    await user.click(screen.getByRole("button", { name: "Confirm selection" }));

    expect(await screen.findByText("Saved to catalog")).toBeVisible();
    expect(requests).toEqual([
      { confirmSimilarity: false, token: "metadata-token-tmdb" },
      { confirmSimilarity: true, token: "metadata-confirmation-token" },
    ]);
  });

  it("clears stale results when the returned similarity confirmation token expires", async () => {
    useBaseHandlers();
    const tokens: string[] = [];
    server.use(
      http.post(
        `${baseUrl}/v1/metadata-selections/:token`,
        async ({ params, request }) => {
          tokens.push(String(params.token));
          const body = (await request.json()) as {
            confirm_similarity?: boolean;
          };
          if (params.token === "metadata-token-tmdb") {
            expect(body.confirm_similarity).toBe(false);
            return HttpResponse.json(
              {
                error: {
                  code: "confirmation_required",
                  details: {
                    confirmation_token: "expiring-confirmation-token",
                    kind: "similarity",
                  },
                  request_id: "confirm-expiring",
                },
              },
              { status: 409 },
            );
          }
          expect(params.token).toBe("expiring-confirmation-token");
          expect(body.confirm_similarity).toBe(true);
          return HttpResponse.json(
            { error: { code: "selection_expired", request_id: "expired-1" } },
            { status: 410 },
          );
        },
      ),
    );
    const user = userEvent.setup();
    renderPage();
    const tmdb = await reachResults(user);
    await user.click(
      within(within(tmdb).getByRole("article", { name: /Arrival/ })).getByRole(
        "button",
        { name: "Select" },
      ),
    );
    await user.click(
      await screen.findByRole("button", { name: "Confirm selection" }),
    );

    const expired = await screen.findByRole("alert");
    expect(expired).toHaveTextContent("The selection expired. Search again.");
    expect(expired).not.toHaveTextContent("Search failed");
    expect(
      screen.queryByRole("article", { name: /Arrival/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Title" })).toBeVisible();
    expect(tokens).toEqual([
      "metadata-token-tmdb",
      "expiring-confirmation-token",
    ]);
  });
});
