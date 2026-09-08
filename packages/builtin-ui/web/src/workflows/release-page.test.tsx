import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
  acquisitions,
  downloadDestinations,
  releaseResults,
  sessions,
} from "../mocks/fixtures";

const baseUrl = "http://localhost/api/control";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(appRoutes, {
    initialEntries: ["/items/arrival-2016/releases"],
  });
  render(
    <I18nextProvider i18n={createUiI18n("en")}>
      <QueryClientProvider client={queryClient}>
        <MantineProvider>
          <ControlProvider client={createControlClient({ baseUrl })}>
            <RouterProvider router={router} />
          </ControlProvider>
        </MantineProvider>
      </QueryClientProvider>
    </I18nextProvider>,
  );
  return router;
}

function useSession() {
  server.use(
    http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
  );
}

describe("ReleasePage", () => {
  it("retries the failed release search snapshot after the editable fields change", async () => {
    useSession();
    const requests: unknown[] = [];
    let attempts = 0;
    server.use(
      http.post(
        `${baseUrl}/v1/media-items/:itemId/release-searches`,
        async ({ request }) => {
          requests.push(await request.json());
          attempts += 1;
          if (attempts === 1) {
            return HttpResponse.json(
              { error: { code: "internal_error", request_id: "release-1" } },
              { status: 500 },
            );
          }
          return HttpResponse.json(releaseResults);
        },
      ),
    );
    const user = userEvent.setup();
    renderPage();

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    const indexerInput = screen.getByRole("textbox", {
      name: "Prowlarr indexer IDs (optional)",
    });
    await user.type(queryInput, "Failed query");
    await user.type(indexerInput, "7");
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Media Finder could not complete the request.",
    );

    await user.clear(queryInput);
    await user.type(queryInput, "Current query");
    await user.clear(indexerInput);
    await user.type(indexerInput, "12");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("radio", { name: /Arrival\.2016/ });
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Results for “Current query”",
    );
    await screen.findByRole("radio", { name: /Arrival\.2016/ });

    expect(requests).toEqual([
      { indexer_ids: [7], query: "Failed query" },
      { indexer_ids: [7], query: "Failed query" },
      { indexer_ids: [12], query: "Current query" },
    ]);
  });

  it("clears the selected release and destination before a replacement search settles", async () => {
    useSession();
    let searchCount = 0;
    let finishReplacement: ((response: Response) => void) | undefined;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        searchCount += 1;
        if (searchCount === 1) return HttpResponse.json(releaseResults);
        return new Promise<Response>((resolve) => {
          finishReplacement = resolve;
        });
      }),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(downloadDestinations),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    await user.type(queryInput, "Arrival");
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    await user.click(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    );
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Destination" }),
      "movies",
    );

    await user.clear(queryInput);
    await user.type(queryInput, "Replacement");
    await user.click(screen.getByRole("button", { name: "Search releases" }));

    expect(
      screen.queryByRole("radio", { name: /Arrival\.2016/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: "Destination" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    ).toBeDisabled();
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Searching for “Replacement”",
    );

    finishReplacement?.(HttpResponse.json(releaseResults));
    expect(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    ).toBeVisible();
  });

  it("starts only one release search while the search is pending", async () => {
    useSession();
    let requests = 0;
    let finishSearch: ((response: Response) => void) | undefined;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        requests += 1;
        return new Promise<Response>((resolve) => {
          finishSearch = resolve;
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "Arrival",
    );
    const search = screen.getByRole("button", { name: "Search releases" });
    await user.click(search);
    await user.click(search);

    expect(requests).toBe(1);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Searching for “Arrival”",
    );
    finishSearch?.(HttpResponse.json(releaseResults));
    expect(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    ).toBeVisible();
  });

  it("does not start a release search while acquisition submission is pending", async () => {
    useSession();
    let searches = 0;
    let finishAcquisition: ((response: Response) => void) | undefined;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        searches += 1;
        return HttpResponse.json(releaseResults);
      }),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(downloadDestinations),
      ),
      http.post(
        `${baseUrl}/v1/acquisitions`,
        () =>
          new Promise<Response>((resolve) => {
            finishAcquisition = resolve;
          }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    await user.type(queryInput, "Arrival");
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    await user.click(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    );
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Destination" }),
      "movies",
    );
    await user.click(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    );
    await user.clear(queryInput);
    await user.type(queryInput, "Blocked search");
    await user.keyboard("{Enter}");

    expect(searches).toBe(1);
    finishAcquisition?.(
      HttpResponse.json(acquisitions.pending, { status: 201 }),
    );
    expect(
      await screen.findByText("Pending — may require manual reconciliation"),
    ).toBeVisible();
  });

  it("locks the selected destination while acquisition preflight is pending", async () => {
    useSession();
    let destinationReads = 0;
    let finishPreflight: ((response: Response) => void) | undefined;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        if (destinationReads === 1) {
          return HttpResponse.json(downloadDestinations);
        }
        return new Promise<Response>((resolve) => {
          finishPreflight = resolve;
        });
      }),
      http.post(`${baseUrl}/v1/acquisitions`, () =>
        HttpResponse.json(acquisitions.pending, { status: 201 }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "Arrival",
    );
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    await user.click(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    );
    const destination = await screen.findByRole("combobox", {
      name: "Destination",
    });
    await user.selectOptions(destination, "movies");
    await user.click(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    );

    expect(destination).toBeDisabled();
    finishPreflight?.(HttpResponse.json(downloadDestinations));
    expect(
      await screen.findByText("Pending — may require manual reconciliation"),
    ).toBeVisible();
  });

  it("returns focus to search after a retry succeeds", async () => {
    useSession();
    let attempts = 0;
    let finishRetry: ((response: Response) => void) | undefined;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        attempts += 1;
        if (attempts === 1) {
          return HttpResponse.json(
            { error: { code: "internal_error", request_id: "release-1" } },
            { status: 500 },
          );
        }
        return new Promise<Response>((resolve) => {
          finishRetry = resolve;
        });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "Arrival",
    );
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    const retry = await screen.findByRole("button", { name: "Retry" });
    await user.click(retry);

    finishRetry?.(HttpResponse.json(releaseResults));
    const search = await screen.findByRole("button", {
      name: "Search releases",
    });
    await waitFor(() => expect(search).toHaveFocus());
  });

  it("ignores a release-search response after navigation changes the item", async () => {
    useSession();
    let requests = 0;
    let finishSearch: ((response: Response) => void) | undefined;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        requests += 1;
        if (requests === 1) {
          return new Promise<Response>((resolve) => {
            finishSearch = resolve;
          });
        }
        return HttpResponse.json(releaseResults);
      }),
    );
    const user = userEvent.setup();
    const router = renderPage();

    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "Arrival",
    );
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    await screen.findByRole("status");
    await router.navigate("/items/dark-2017/releases");
    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    const search = screen.getByRole("button", { name: "Search releases" });
    await waitFor(() => expect(search).toBeEnabled());
    await user.clear(queryInput);
    await user.type(queryInput, "Dark");
    await user.click(search);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Results for “Dark”",
    );

    finishSearch?.(HttpResponse.json(releaseResults));
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent(
        "Results for “Dark”",
      );
    });
  });

  it("shows an explicit empty outcome only after a successful release search", async () => {
    useSession();
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json([]),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "No matches",
    );
    await user.click(screen.getByRole("button", { name: "Search releases" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "No results for “No matches”",
    );
  });

  it("forwards valid optional Prowlarr indexer identifiers", async () => {
    useSession();
    let requestBody: unknown;
    server.use(
      http.post(
        `${baseUrl}/v1/media-items/:itemId/release-searches`,
        async ({ request }) => {
          requestBody = await request.json();
          return HttpResponse.json(releaseResults);
        },
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "Arrival",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Prowlarr indexer IDs (optional)" }),
      "7, 12",
    );
    await user.click(screen.getByRole("button", { name: "Search releases" }));

    expect(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    ).toBeVisible();
    expect(requestBody).toEqual({ indexer_ids: [7, 12], query: "Arrival" });
  });

  it("rejects malformed Prowlarr indexer identifiers before searching", async () => {
    useSession();
    let searchRequests = 0;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        searchRequests += 1;
        return HttpResponse.json(releaseResults);
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "Arrival",
    );
    await user.type(
      screen.getByRole("textbox", { name: "Prowlarr indexer IDs (optional)" }),
      "7, invalid",
    );
    await user.click(screen.getByRole("button", { name: "Search releases" }));

    const indexerInput = screen.getByRole("textbox", {
      name: "Prowlarr indexer IDs (optional)",
    });
    expect(indexerInput).toHaveAttribute("aria-invalid", "true");
    expect(
      screen.getByText("Enter comma-separated numeric indexer IDs."),
    ).toBeVisible();
    expect(searchRequests).toBe(0);
  });

  it("requires explicit release and live destination selection before submission", async () => {
    useSession();
    let destinationReads = 0;
    let submission: Record<string, unknown> | undefined;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        return HttpResponse.json(downloadDestinations);
      }),
      http.post(`${baseUrl}/v1/acquisitions`, async ({ request }) => {
        submission = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(acquisitions.pending, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();
    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "Arrival",
    );
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    expect(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    ).toBeDisabled();
    await user.click(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    );
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Destination" }),
      "movies",
    );
    await user.click(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    );

    expect(destinationReads).toBeGreaterThan(1);
    expect(submission).toMatchObject({
      destination: "movies",
      media_item_id: "arrival-2016",
      release_token: "release-token-1",
    });
    expect(submission?.idempotency_key).toEqual(expect.any(String));
    expect(
      await screen.findByText("Pending — may require manual reconciliation"),
    ).toBeVisible();
  });

  it.each([
    ["submitted", "Submitted"],
    ["failed", "Failed"],
  ] as const)(
    "renders the %s acquisition result without progress claims",
    async (status, label) => {
      useSession();
      server.use(
        http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
          HttpResponse.json(releaseResults),
        ),
        http.get(`${baseUrl}/v1/download-destinations`, () =>
          HttpResponse.json(downloadDestinations),
        ),
        http.post(`${baseUrl}/v1/acquisitions`, () =>
          HttpResponse.json(acquisitions[status], { status: 201 }),
        ),
      );
      const user = userEvent.setup();
      renderPage();
      await user.type(
        await screen.findByRole("searchbox", { name: "Release query" }),
        "Arrival",
      );
      await user.click(screen.getByRole("button", { name: "Search releases" }));
      await user.click(
        await screen.findByRole("radio", { name: /Arrival\.2016/ }),
      );
      await user.selectOptions(
        await screen.findByRole("combobox", { name: "Destination" }),
        "movies",
      );
      await user.click(
        screen.getByRole("button", { name: "Confirm acquisition" }),
      );

      expect(await screen.findByText(label)).toBeVisible();
      expect(screen.queryByText(/progress/i)).not.toBeInTheDocument();
    },
  );

  it("returns safely to release search when a selection token expires", async () => {
    useSession();
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(downloadDestinations),
      ),
      http.post(`${baseUrl}/v1/acquisitions`, () =>
        HttpResponse.json(
          {
            error: {
              code: "release_search_token_expired",
              request_id: "release-expired",
            },
          },
          { status: 410 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();
    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "Arrival",
    );
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    await user.click(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    );
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Destination" }),
      "movies",
    );
    await user.click(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The release search expired. Search again.",
    );
    expect(
      screen.queryByRole("radio", { name: /Arrival\.2016/ }),
    ).not.toBeInTheDocument();
  });

  it("reports a safe error and blocks submission when live destinations fail", async () => {
    useSession();
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(
          {
            error: {
              code: "download_client_unavailable",
              request_id: "download-1",
            },
          },
          { status: 503 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await user.type(
      await screen.findByRole("searchbox", { name: "Release query" }),
      "Arrival",
    );
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    await user.click(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The download client is unavailable.",
    );
    expect(
      screen.queryByRole("combobox", { name: "Destination" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    ).toBeDisabled();
  });
});
