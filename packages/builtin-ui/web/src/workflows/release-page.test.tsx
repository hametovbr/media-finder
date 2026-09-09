import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { setupServer } from "msw/node";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import {
  afterAll,
  afterEach,
  beforeAll,
  describe,
  expect,
  it,
  vi,
} from "vitest";

import { createControlClient } from "../api/control-client";
import { ControlProvider } from "../api/control-provider";
import { appRoutes } from "../app-router";
import { createUiI18n } from "../i18n";
import {
  acquisitions,
  downloadDestinations,
  mediaDetail,
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
  return { queryClient, router };
}

function useSession() {
  server.use(
    http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
    http.get(`${baseUrl}/v1/media-items/:itemId`, () =>
      HttpResponse.json(mediaDetail),
    ),
  );
}

async function enterReleaseQuery(
  user: ReturnType<typeof userEvent.setup>,
  value: string,
) {
  const input = await screen.findByRole("searchbox", {
    name: "Release query",
  });
  await waitFor(() => expect(input).toHaveValue("Arrival"));
  await user.clear(input);
  await user.type(input, value);
  return input;
}

describe("ReleasePage", () => {
  it("prefills the release query from saved context without searching", async () => {
    useSession();
    let searchRequests = 0;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        searchRequests += 1;
        return HttpResponse.json(releaseResults);
      }),
    );
    renderPage();

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    await waitFor(() => expect(queryInput).toHaveValue("Arrival"));
    expect(
      screen.getByRole("link", { name: "Back to media item" }),
    ).toHaveAttribute("href", `/items/${mediaDetail.id}`);
    expect(searchRequests).toBe(0);
  });

  it("preserves an edited query when saved context arrives late", async () => {
    useSession();
    let finishContext: ((response: Response) => void) | undefined;
    server.use(
      http.get(
        `${baseUrl}/v1/media-items/:itemId`,
        () =>
          new Promise<Response>((resolve) => {
            finishContext = resolve;
          }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    expect(finishContext).toBeTypeOf("function");
    await user.type(queryInput, "Manual query");
    expect(queryInput).toHaveValue("Manual query");

    finishContext?.(HttpResponse.json(mediaDetail));
    expect(await screen.findByText("Saved work")).toBeVisible();
    await waitFor(() => expect(queryInput).toHaveValue("Manual query"));
  });

  it("preserves an edited query across context refetch and metadata-locale change", async () => {
    useSession();
    const contextLocales: string[] = [];
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, ({ request }) => {
        contextLocales.push(
          new URL(request.url).searchParams.get("locale") ?? "",
        );
        return HttpResponse.json(mediaDetail);
      }),
    );
    const user = userEvent.setup();
    const { queryClient } = renderPage();
    const queryInput = await enterReleaseQuery(user, "Manual query");

    await queryClient.refetchQueries({
      queryKey: ["control", "media-item", mediaDetail.id, "en"],
    });
    expect(queryInput).toHaveValue("Manual query");

    queryClient.setQueryData(["control", "session"], {
      ...sessions.en,
      metadata_locale: "ru",
    });
    await waitFor(() => expect(contextLocales).toContain("ru"));
    expect(queryInput).toHaveValue("Manual query");
  });

  it("prefills from the original title when localized titles are unavailable", async () => {
    useSession();
    const fallbackDetail = {
      ...mediaDetail,
      metadata: {
        ...mediaDetail.metadata,
        original_title: "Original fallback",
        titles: { en: "", ru: "" },
      },
    };
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, () =>
        HttpResponse.json(fallbackDetail),
      ),
    );
    renderPage();

    await waitFor(() =>
      expect(
        screen.getByRole("searchbox", { name: "Release query" }),
      ).toHaveValue("Original fallback"),
    );
  });

  it("allows context recovery without losing an edited query", async () => {
    useSession();
    let attempts = 0;
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, () => {
        attempts += 1;
        return attempts === 1
          ? HttpResponse.json(
              { error: { code: "media_item_not_found", request_id: "item-1" } },
              { status: 404 },
            )
          : HttpResponse.json(mediaDetail);
      }),
    );
    const user = userEvent.setup();
    renderPage();

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    await user.type(queryInput, "Manual query");
    expect(
      await screen.findByText("The requested media item was not found."),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Search releases" }),
    ).toBeDisabled();
    await user.click(
      screen.getByRole("button", { name: "Retry loading saved work" }),
    );

    await screen.findByText("Saved work");
    expect(queryInput).toHaveValue("Manual query");
    expect(
      screen.getByRole("button", { name: "Search releases" }),
    ).toBeEnabled();
    expect(attempts).toBe(2);
  });

  it("rejects release queries longer than 500 characters without searching", async () => {
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

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    await waitFor(() => expect(queryInput).toHaveValue("Arrival"));
    fireEvent.change(queryInput, { target: { value: "x".repeat(501) } });
    await user.click(screen.getByRole("button", { name: "Search releases" }));

    expect(queryInput).toHaveAttribute("aria-invalid", "true");
    expect(
      screen.getByText("Release query must be 500 characters or fewer."),
    ).toBeVisible();
    expect(searchRequests).toBe(0);
  });

  it("resets contextual draft and selection when moving to another work", async () => {
    useSession();
    const darkDetail = {
      ...mediaDetail,
      external_id: "dark-external",
      id: "dark-2017",
      metadata: {
        ...mediaDetail.metadata,
        titles: { ...mediaDetail.metadata.titles, en: "Dark" },
      },
    };
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, ({ params }) =>
        HttpResponse.json(
          params.itemId === darkDetail.id ? darkDetail : mediaDetail,
        ),
      ),
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(downloadDestinations),
      ),
    );
    const user = userEvent.setup();
    const { router } = renderPage();

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    await waitFor(() => expect(queryInput).toHaveValue("Arrival"));
    await user.clear(queryInput);
    await user.type(queryInput, "Custom query");
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    await user.click(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    );

    await router.navigate(`/items/${darkDetail.id}/releases`);
    await waitFor(() =>
      expect(
        screen.getByRole("searchbox", { name: "Release query" }),
      ).toHaveValue("Dark"),
    );
    expect(
      screen.queryByRole("radio", { name: /Arrival\.2016/ }),
    ).not.toBeInTheDocument();
  });

  it("shows labeled comparison facts and keeps advanced filters through collapse", async () => {
    useSession();
    const comparisonResults = [
      {
        indexer: null,
        seeders: null,
        size: null,
        title: "A very long release title that still wraps on narrow screens",
        token: "release-unknown",
      },
      {
        indexer: "Example Indexer",
        seeders: 0,
        size: 9007199254740991,
        title: "Portable maximum",
        token: "release-maximum",
      },
    ];
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(comparisonResults),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    await waitFor(() => expect(queryInput).toHaveValue("Arrival"));
    await user.click(screen.getByRole("button", { name: "Advanced filters" }));
    const indexerInput = screen.getByRole("textbox", {
      name: "Prowlarr indexer IDs (optional)",
    });
    await user.type(indexerInput, "7");
    await user.click(screen.getByRole("button", { name: "Advanced filters" }));
    expect(indexerInput).toHaveValue("7");
    expect(
      screen.getByRole("button", { name: "Advanced filters" }),
    ).toHaveAttribute("aria-expanded", "false");

    await user.clear(queryInput);
    await user.type(queryInput, "Arrival");
    await user.click(screen.getByRole("button", { name: "Search releases" }));

    expect((await screen.findAllByText("Indexer:")).length).toBe(2);
    expect(screen.getAllByText("Unknown").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Seeders:").length).toBe(2);
    expect(screen.getByText("9007199254740991 bytes")).toBeInTheDocument();
    const maximumRadio = screen.getByRole("radio", {
      name: /Portable maximum/,
    });
    expect(maximumRadio).toBeVisible();
    const factsId = maximumRadio.getAttribute("aria-describedby");
    expect(factsId).not.toBeNull();
    expect(document.getElementById(factsId ?? "")).toHaveTextContent(
      "Indexer: Example Indexer",
    );
    expect(document.getElementById(factsId ?? "")).toHaveTextContent("Size:");
    expect(document.getElementById(factsId ?? "")).toHaveTextContent(
      "9007199254740991 bytes",
    );
    expect(document.getElementById(factsId ?? "")).toHaveTextContent(
      "Seeders: 0",
    );
  });

  it("reveals and focuses an invalid advanced indexer filter", async () => {
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

    const queryInput = await screen.findByRole("searchbox", {
      name: "Release query",
    });
    await waitFor(() => expect(queryInput).toHaveValue("Arrival"));
    await user.click(screen.getByRole("button", { name: "Advanced filters" }));
    const indexerInput = screen.getByRole("textbox", {
      name: "Prowlarr indexer IDs (optional)",
    });
    await user.type(indexerInput, "not-a-number");
    await user.click(screen.getByRole("button", { name: "Advanced filters" }));
    await user.click(screen.getByRole("button", { name: "Search releases" }));

    expect(indexerInput).toHaveAttribute("aria-invalid", "true");
    expect(indexerInput).toHaveFocus();
    expect(
      screen.getByRole("button", { name: "Advanced filters" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(searchRequests).toBe(0);
  });

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
    await waitFor(() => expect(queryInput).toHaveValue("Arrival"));
    await user.clear(queryInput);
    await user.click(screen.getByRole("button", { name: "Advanced filters" }));
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
    await waitFor(() => expect(queryInput).toHaveValue("Arrival"));
    await user.clear(queryInput);
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

    await enterReleaseQuery(user, "Arrival");
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
    await waitFor(() => expect(queryInput).toHaveValue("Arrival"));
    await user.clear(queryInput);
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(searches).toBe(1);
    expect(queryInput).toBeDisabled();
    finishAcquisition?.(
      HttpResponse.json(acquisitions.pending, { status: 201 }),
    );
    expect(await screen.findByText("Pending")).toBeVisible();
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

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(destination).toBeDisabled();
    finishPreflight?.(HttpResponse.json(downloadDestinations));
    expect(await screen.findByText("Pending")).toBeVisible();
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

    await enterReleaseQuery(user, "Arrival");
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
    const { router } = renderPage();

    await enterReleaseQuery(user, "Arrival");
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    await screen.findByRole("status");
    await router.navigate("/items/dark-2017/releases");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Search releases" }),
      ).toBeEnabled(),
    );
    const queryInput = screen.getByRole("searchbox", {
      name: "Release query",
    });
    const search = screen.getByRole("button", { name: "Search releases" });
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
    await enterReleaseQuery(user, "No matches");
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

    await enterReleaseQuery(user, "Arrival");
    await user.click(screen.getByRole("button", { name: "Advanced filters" }));
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

    await enterReleaseQuery(user, "Arrival");
    await user.click(screen.getByRole("button", { name: "Advanced filters" }));
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
    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(destinationReads).toBeGreaterThan(1);
    expect(submission).toMatchObject({
      destination: "movies",
      media_item_id: "arrival-2016",
      release_token: "release-token-1",
    });
    expect(submission?.idempotency_key).toEqual(expect.any(String));
    expect(await screen.findByText("Pending")).toBeVisible();
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
      await enterReleaseQuery(user, "Arrival");
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
      await user.click(screen.getByRole("button", { name: "Confirm review" }));

      expect(await screen.findByText(label)).toBeVisible();
      expect(screen.queryByText(/progress/i)).not.toBeInTheDocument();
    },
  );

  it.each([410, 422] as const)(
    "returns safely to release search when a selection token expires (%s)",
    async (status) => {
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
            { status },
          ),
        ),
      );
      const user = userEvent.setup();
      renderPage();
      await enterReleaseQuery(user, "Arrival");
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
      await user.click(screen.getByRole("button", { name: "Confirm review" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The release search expired. Search again.",
      );
      expect(
        screen.queryByRole("radio", { name: /Arrival\.2016/ }),
      ).not.toBeInTheDocument();
    },
  );

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

    await enterReleaseQuery(user, "Arrival");
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

  it("does not post when the live destination preflight refetch fails", async () => {
    useSession();
    let destinationReads = 0;
    let submissions = 0;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        return destinationReads === 1
          ? HttpResponse.json(downloadDestinations)
          : HttpResponse.json(
              {
                error: {
                  code: "download_client_unavailable",
                  request_id: "download-preflight",
                },
              },
              { status: 503 },
            );
      }),
      http.post(`${baseUrl}/v1/acquisitions`, () => {
        submissions += 1;
        return HttpResponse.json(acquisitions.pending, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(
      await screen.findAllByText("The download client is unavailable."),
    ).toHaveLength(1);
    expect(destinationReads).toBe(2);
    expect(submissions).toBe(0);
  });

  it("reviews a frozen work, release and destination and cancels with focus restored", async () => {
    useSession();
    let submissions = 0;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(downloadDestinations),
      ),
      http.post(`${baseUrl}/v1/acquisitions`, () => {
        submissions += 1;
        return HttpResponse.json(acquisitions.pending, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
    await user.click(screen.getByRole("button", { name: "Search releases" }));
    await user.click(
      await screen.findByRole("radio", { name: /Arrival\.2016/ }),
    );
    await user.selectOptions(
      await screen.findByRole("combobox", { name: "Destination" }),
      "movies",
    );

    const reviewTrigger = screen.getByRole("button", {
      name: "Confirm acquisition",
    });
    await user.click(reviewTrigger);
    const dialog = await screen.findByRole("dialog", {
      name: "Review acquisition",
    });
    expect(dialog).toHaveTextContent("Arrival");
    expect(dialog).toHaveTextContent("Arrival.2016.1080p.BluRay");
    expect(dialog).toHaveTextContent("Movies");
    expect(screen.getByRole("button", { name: "Cancel review" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Cancel review" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(reviewTrigger).toHaveFocus();

    await user.click(reviewTrigger);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(reviewTrigger).toHaveFocus();
    expect(submissions).toBe(0);
  });

  it("admits one confirmation and abandons a pending destination preflight without posting", async () => {
    useSession();
    let destinationReads = 0;
    let finishPreflight: ((response: Response) => void) | undefined;
    let submissions = 0;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        if (destinationReads === 1)
          return HttpResponse.json(downloadDestinations);
        return new Promise<Response>((resolve) => {
          finishPreflight = resolve;
        });
      }),
      http.post(`${baseUrl}/v1/acquisitions`, () => {
        submissions += 1;
        return HttpResponse.json(acquisitions.pending, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    const { router } = renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(destinationReads).toBe(2);
    expect(submissions).toBe(0);
    expect(
      screen.queryByRole("combobox", { name: "Destination" }),
    ).not.toBeInTheDocument();

    await router.navigate("/items/dark-2017/releases");
    finishPreflight?.(HttpResponse.json(downloadDestinations));
    await waitFor(() => expect(submissions).toBe(0));
  });

  it("reopens destination selection after a post-preflight destination race with a new key", async () => {
    useSession();
    let destinationReads = 0;
    let submissions = 0;
    const requests: Record<string, unknown>[] = [];
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        return HttpResponse.json(
          destinationReads >= 3
            ? [downloadDestinations[1]]
            : downloadDestinations,
        );
      }),
      http.post(`${baseUrl}/v1/acquisitions`, async ({ request }) => {
        submissions += 1;
        requests.push((await request.json()) as Record<string, unknown>);
        if (submissions === 1) {
          return HttpResponse.json(
            {
              error: {
                code: "download_destination_unavailable",
                request_id: "destination-race",
              },
            },
            { status: 409 },
          );
        }
        return HttpResponse.json(acquisitions.submitted, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The selected destination is no longer available.",
    );
    expect(destinationReads).toBeGreaterThanOrEqual(3);
    expect(screen.getByRole("combobox", { name: "Destination" })).toHaveValue(
      "",
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Destination" }),
      "archive",
    );
    await user.click(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm review" }));
    expect(await screen.findByText("Submitted")).toBeVisible();
    expect(requests).toHaveLength(2);
    expect(requests[0]!.release_token).toBe(requests[1]!.release_token);
    expect(requests[0]!.idempotency_key).not.toBe(requests[1]!.idempotency_key);
    expect(requests[1]!.destination).toBe("archive");
  });

  it("locks selection and review while the destination race refresh is pending", async () => {
    useSession();
    let destinationReads = 0;
    let finishRefresh: ((response: Response) => void) | undefined;
    let submissions = 0;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        if (destinationReads === 3) {
          return new Promise<Response>((resolve) => {
            finishRefresh = resolve;
          });
        }
        return HttpResponse.json(downloadDestinations);
      }),
      http.post(`${baseUrl}/v1/acquisitions`, () => {
        submissions += 1;
        return submissions === 1
          ? HttpResponse.json(
              {
                error: {
                  code: "download_destination_unavailable",
                  request_id: "destination-race-held",
                },
              },
              { status: 409 },
            )
          : HttpResponse.json(acquisitions.submitted, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));
    await waitFor(() => expect(destinationReads).toBe(3));
    expect(finishRefresh).toBeTypeOf("function");

    expect(
      screen.getByRole("button", { name: "Search releases" }),
    ).toBeDisabled();
    expect(
      screen.queryByRole("combobox", { name: "Destination" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    ).toBeDisabled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(submissions).toBe(1);

    finishRefresh?.(HttpResponse.json([{ key: "archive", label: "Archive" }]));
  });

  it("abandons a destination race refresh without late feedback after navigation", async () => {
    useSession();
    let destinationReads = 0;
    let finishRefresh: ((response: Response) => void) | undefined;
    let submissions = 0;
    const darkDetail = {
      ...mediaDetail,
      id: "dark-2017",
      metadata: {
        ...mediaDetail.metadata,
        titles: { ...mediaDetail.metadata.titles, en: "Dark" },
      },
    };
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, ({ params }) =>
        HttpResponse.json(
          params.itemId === darkDetail.id ? darkDetail : mediaDetail,
        ),
      ),
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        if (destinationReads === 3) {
          return new Promise<Response>((resolve) => {
            finishRefresh = resolve;
          });
        }
        return HttpResponse.json(downloadDestinations);
      }),
      http.post(`${baseUrl}/v1/acquisitions`, () => {
        submissions += 1;
        return HttpResponse.json(
          {
            error: {
              code: "download_destination_unavailable",
              request_id: "destination-abandon",
            },
          },
          { status: 409 },
        );
      }),
    );
    const user = userEvent.setup();
    const { queryClient, router } = renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));
    await waitFor(() => expect(destinationReads).toBe(3));

    await router.navigate("/items/dark-2017/releases");
    await screen.findByText("Dark");
    await act(async () => {
      finishRefresh?.(HttpResponse.json(downloadDestinations));
    });
    await waitFor(() =>
      expect(
        queryClient.isFetching({
          queryKey: ["control", "download-destinations", "release-token-1"],
        }),
      ).toBe(0),
    );
    expect(submissions).toBe(1);
    expect(
      screen.queryByText("The selected destination is no longer available."),
    ).not.toBeInTheDocument();
  });

  it("recovers from a failed destination reload before requiring a new selection and key", async () => {
    useSession();
    let destinationReads = 0;
    let submissions = 0;
    const requests: Record<string, unknown>[] = [];
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        if (destinationReads === 3) {
          return HttpResponse.json(
            {
              error: {
                code: "download_client_unavailable",
                request_id: "destination-reload",
              },
            },
            { status: 503 },
          );
        }
        return HttpResponse.json(
          destinationReads >= 4
            ? [downloadDestinations[1]]
            : downloadDestinations,
        );
      }),
      http.post(`${baseUrl}/v1/acquisitions`, async ({ request }) => {
        submissions += 1;
        requests.push((await request.json()) as Record<string, unknown>);
        return submissions === 1
          ? HttpResponse.json(
              {
                error: {
                  code: "download_destination_unavailable",
                  request_id: "destination-race",
                },
              },
              { status: 409 },
            )
          : HttpResponse.json(acquisitions.submitted, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    const retryDestinations = await screen.findByRole("button", {
      name: "Retry destinations",
    });
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(destinationReads).toBe(3);
    await user.click(retryDestinations);
    const destinationSelect = await screen.findByRole("combobox", {
      name: "Destination",
    });
    expect(destinationSelect).toHaveValue("");
    await user.selectOptions(destinationSelect, "archive");
    await user.click(
      screen.getByRole("button", { name: "Confirm acquisition" }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(await screen.findByText("Submitted")).toBeVisible();
    expect(destinationReads).toBe(5);
    expect(requests).toHaveLength(2);
    expect(requests[0]!.release_token).toBe(requests[1]!.release_token);
    expect(requests[0]!.idempotency_key).not.toBe(requests[1]!.idempotency_key);
    expect(requests[1]!.destination).toBe("archive");
  });

  it("retries an uncertain request with the exact payload and key without preflight or automatic replay", async () => {
    useSession();
    let destinationReads = 0;
    let searchRequests = 0;
    let submissions = 0;
    const requests: Record<string, unknown>[] = [];
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        searchRequests += 1;
        return HttpResponse.json(releaseResults);
      }),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        return HttpResponse.json(downloadDestinations);
      }),
      http.post(`${baseUrl}/v1/acquisitions`, async ({ request }) => {
        submissions += 1;
        requests.push((await request.json()) as Record<string, unknown>);
        if (submissions === 1) {
          return HttpResponse.json(
            { error: { code: "internal_error", request_id: "uncertain-1" } },
            { status: 500 },
          );
        }
        return HttpResponse.json(acquisitions.submitted, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(
      await screen.findByRole("button", { name: "Retry request" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Search releases" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("combobox", { name: "Destination" }),
    ).toBeDisabled();
    expect(destinationReads).toBe(2);
    expect(searchRequests).toBe(1);

    await user.click(screen.getByRole("button", { name: "Retry request" }));
    expect(await screen.findByText("Submitted")).toBeVisible();
    expect(submissions).toBe(2);
    expect(destinationReads).toBe(2);
    expect(requests[0]).toEqual(requests[1]);
  });

  it("retries a network-uncertain request with the exact payload and key", async () => {
    useSession();
    let destinationReads = 0;
    let searchRequests = 0;
    let submissions = 0;
    const requests: Record<string, unknown>[] = [];
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        searchRequests += 1;
        return HttpResponse.json(releaseResults);
      }),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        return HttpResponse.json(downloadDestinations);
      }),
      http.post(`${baseUrl}/v1/acquisitions`, async ({ request }) => {
        submissions += 1;
        requests.push((await request.json()) as Record<string, unknown>);
        return submissions === 1
          ? HttpResponse.error()
          : HttpResponse.json(acquisitions.submitted, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(
      await screen.findByRole("button", { name: "Retry request" }),
    ).toBeVisible();
    expect(destinationReads).toBe(2);
    expect(searchRequests).toBe(1);
    await user.click(screen.getByRole("button", { name: "Retry request" }));
    expect(await screen.findByText("Submitted")).toBeVisible();
    expect(submissions).toBe(2);
    expect(destinationReads).toBe(2);
    expect(searchRequests).toBe(1);
    expect(requests[0]).toEqual(requests[1]);
  });

  it.each([
    ["media_item_not_found", 404, "The requested media item was not found."],
    ["request_invalid", 422, "The request is invalid."],
  ] as const)(
    "shows a definitive %s diagnostic without offering an uncertain retry",
    async (code, status, diagnostic) => {
      useSession();
      let submissions = 0;
      server.use(
        http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
          HttpResponse.json(releaseResults),
        ),
        http.get(`${baseUrl}/v1/download-destinations`, () =>
          HttpResponse.json(downloadDestinations),
        ),
        http.post(`${baseUrl}/v1/acquisitions`, () => {
          submissions += 1;
          return HttpResponse.json(
            { error: { code, request_id: `definitive-${code}` } },
            { status },
          );
        }),
      );
      const user = userEvent.setup();
      renderPage();

      await enterReleaseQuery(user, "Arrival");
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
      await user.click(screen.getByRole("button", { name: "Confirm review" }));

      expect(await screen.findByText(diagnostic)).toBeVisible();
      expect(
        screen.queryByRole("button", { name: "Retry request" }),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText(/The request may still be accepted/),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("radio", { name: /Arrival\.2016/ }),
      ).toBeVisible();
      expect(submissions).toBe(1);
    },
  );

  it("keeps an unclassified proxy 408 failure uncertain", async () => {
    useSession();
    let submissions = 0;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(downloadDestinations),
      ),
      http.post(`${baseUrl}/v1/acquisitions`, () => {
        submissions += 1;
        return HttpResponse.json(
          { error: { code: "proxy_timeout", request_id: "proxy-408" } },
          { status: 408 },
        );
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(
      await screen.findByRole("button", { name: "Retry request" }),
    ).toBeVisible();
    expect(submissions).toBe(1);
  });

  it.each([
    "download_destination_unavailable",
    "release_search_token_expired",
    "release_selection_invalid",
    "selection_expired",
  ] as const)(
    "keeps %s uncertain when the server returns 500",
    async (code) => {
      useSession();
      let destinationReads = 0;
      let submissions = 0;
      const requests: Record<string, unknown>[] = [];
      server.use(
        http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
          HttpResponse.json(releaseResults),
        ),
        http.get(`${baseUrl}/v1/download-destinations`, () => {
          destinationReads += 1;
          return HttpResponse.json(downloadDestinations);
        }),
        http.post(`${baseUrl}/v1/acquisitions`, async ({ request }) => {
          submissions += 1;
          requests.push((await request.json()) as Record<string, unknown>);
          return submissions === 1
            ? HttpResponse.json(
                { error: { code, request_id: `special-500-${code}` } },
                { status: 500 },
              )
            : HttpResponse.json(acquisitions.submitted, { status: 201 });
        }),
      );
      const user = userEvent.setup();
      renderPage();

      await enterReleaseQuery(user, "Arrival");
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
      await user.click(screen.getByRole("button", { name: "Confirm review" }));

      expect(
        await screen.findByRole("button", { name: "Retry request" }),
      ).toBeVisible();
      expect(submissions).toBe(1);
      expect(destinationReads).toBe(2);

      await user.click(screen.getByRole("button", { name: "Retry request" }));
      expect(await screen.findByText("Submitted")).toBeVisible();
      expect(submissions).toBe(2);
      expect(destinationReads).toBe(2);
      expect(requests).toHaveLength(2);
      expect(requests[0]).toEqual(requests[1]);
    },
  );

  it("requires a fresh search and key after a returned failed acquisition", async () => {
    useSession();
    let searchRequests = 0;
    let submissions = 0;
    const requests: Record<string, unknown>[] = [];
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () => {
        searchRequests += 1;
        return HttpResponse.json(
          releaseResults.map((result) => ({
            ...result,
            token: `release-token-${searchRequests}`,
          })),
        );
      }),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(downloadDestinations),
      ),
      http.post(`${baseUrl}/v1/acquisitions`, async ({ request }) => {
        submissions += 1;
        requests.push((await request.json()) as Record<string, unknown>);
        return submissions === 1
          ? HttpResponse.json(acquisitions.failed, { status: 201 })
          : HttpResponse.json(acquisitions.submitted, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));
    expect(await screen.findByText("Failed")).toBeVisible();
    expect(
      screen.queryByRole("radio", { name: /Arrival\.2016/ }),
    ).not.toBeInTheDocument();

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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));
    expect(await screen.findByText("Submitted")).toBeVisible();
    expect(searchRequests).toBe(2);
    expect(requests).toHaveLength(2);
    expect(requests[0]!.release_token).not.toBe(requests[1]!.release_token);
    expect(requests[0]!.idempotency_key).not.toBe(requests[1]!.idempotency_key);
  });

  it("admits only one explicit retry while an uncertain request is pending", async () => {
    useSession();
    let submissions = 0;
    const requests: Record<string, unknown>[] = [];
    const pendingRetries: Array<(response: Response) => void> = [];
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(downloadDestinations),
      ),
      http.post(`${baseUrl}/v1/acquisitions`, async ({ request }) => {
        submissions += 1;
        requests.push((await request.json()) as Record<string, unknown>);
        return submissions === 1
          ? HttpResponse.json(
              { error: { code: "internal_error", request_id: "retry-1" } },
              { status: 500 },
            )
          : new Promise<Response>((resolve) => {
              pendingRetries.push(resolve);
            });
      }),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));
    const retry = await screen.findByRole("button", { name: "Retry request" });

    act(() => {
      fireEvent.click(retry);
      fireEvent.click(retry);
    });
    await waitFor(() => expect(submissions).toBeGreaterThanOrEqual(2));
    expect(submissions).toBe(2);
    pendingRetries.forEach((resolve) =>
      resolve(HttpResponse.json(acquisitions.submitted, { status: 201 })),
    );
    expect(await screen.findByText("Submitted")).toBeVisible();
    expect(requests).toHaveLength(2);
    expect(requests[0]).toEqual(requests[1]);
  });

  it("keeps review labels frozen through live label changes and returned feedback", async () => {
    useSession();
    let destinationReads = 0;
    server.use(
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () => {
        destinationReads += 1;
        return HttpResponse.json(
          destinationReads === 1
            ? downloadDestinations
            : [{ key: "movies", label: "Changed destination" }],
        );
      }),
      http.post(`${baseUrl}/v1/acquisitions`, () =>
        HttpResponse.json(acquisitions.pending, { status: 201 }),
      ),
    );
    const user = userEvent.setup();
    const { queryClient } = renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    const dialog = await screen.findByRole("dialog", {
      name: "Review acquisition",
    });
    expect(dialog).toHaveTextContent("Arrival");
    expect(dialog).toHaveTextContent("Movies");

    queryClient.setQueryData(["control", "media-item", mediaDetail.id, "en"], {
      ...mediaDetail,
      metadata: {
        ...mediaDetail.metadata,
        titles: { ...mediaDetail.metadata.titles, en: "Changed work" },
      },
    });
    await user.click(screen.getByRole("button", { name: "Confirm review" }));

    expect(await screen.findByText("Pending")).toBeVisible();
    expect(
      screen
        .getAllByRole("status")
        .some((status) => status.textContent?.includes("Arrival")),
    ).toBe(true);
    expect(screen.getByText("Destination: Movies")).toBeVisible();
    expect(
      screen.queryByText("Destination: Changed destination"),
    ).not.toBeInTheDocument();
  });

  it("shows a returned status before an invalidation refetch settles", async () => {
    useSession();
    let contextReads = 0;
    let finishContext: ((response: Response) => void) | undefined;
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, () => {
        contextReads += 1;
        return contextReads === 1
          ? HttpResponse.json(mediaDetail)
          : new Promise<Response>((resolve) => {
              finishContext = resolve;
            });
      }),
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
      http.get(`${baseUrl}/v1/download-destinations`, () =>
        HttpResponse.json(downloadDestinations),
      ),
      http.post(`${baseUrl}/v1/acquisitions`, () =>
        HttpResponse.json(acquisitions.submitted, { status: 201 }),
      ),
    );
    const user = userEvent.setup();
    renderPage();

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));
    await waitFor(() => expect(contextReads).toBeGreaterThanOrEqual(2));
    const outcomeVisibleBeforeRefetch =
      screen.queryByText("Submitted") !== null;
    finishContext?.(HttpResponse.json(mediaDetail));
    expect(outcomeVisibleBeforeRefetch).toBe(true);
  });

  it("invalidates the abandoned item's caches without showing late feedback on item B", async () => {
    useSession();
    let finishAcquisition: ((response: Response) => void) | undefined;
    const darkDetail = {
      ...mediaDetail,
      id: "dark-2017",
      metadata: {
        ...mediaDetail.metadata,
        titles: { ...mediaDetail.metadata.titles, en: "Dark" },
      },
    };
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, ({ params }) =>
        HttpResponse.json(
          params.itemId === darkDetail.id ? darkDetail : mediaDetail,
        ),
      ),
      http.post(`${baseUrl}/v1/media-items/:itemId/release-searches`, () =>
        HttpResponse.json(releaseResults),
      ),
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
    const { queryClient, router } = renderPage();
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

    await enterReleaseQuery(user, "Arrival");
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
    await user.click(screen.getByRole("button", { name: "Confirm review" }));
    await waitFor(() => expect(finishAcquisition).toBeTypeOf("function"));

    queryClient.setQueryData(["control", "catalog"], { page: "cached" });
    queryClient.setQueryData(
      ["control", "media-item", mediaDetail.id, "en"],
      mediaDetail,
    );
    await router.navigate("/items/dark-2017/releases");
    await screen.findByText("Dark");
    finishAcquisition?.(
      HttpResponse.json(acquisitions.submitted, { status: 201 }),
    );

    await waitFor(() =>
      expect(invalidateQueries).toHaveBeenCalledWith({
        queryKey: ["control", "catalog"],
      }),
    );
    expect(invalidateQueries).toHaveBeenCalledWith({
      queryKey: ["control", "media-item", mediaDetail.id],
    });
    expect(screen.queryByText("Submitted")).not.toBeInTheDocument();
    expect(
      screen.queryByText("The selected destination is no longer available."),
    ).not.toBeInTheDocument();
  });

  it("shows the latest acquisition status and a separate pending explanation", async () => {
    useSession();
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, () =>
        HttpResponse.json({
          ...mediaDetail,
          acquisitions: [acquisitions.pending, acquisitions.submitted],
        }),
      ),
    );
    const { router } = renderPage();
    await screen.findByRole("heading", { name: "Find release" });
    await router.navigate(`/items/${mediaDetail.id}`);

    expect(await screen.findByText("Pending")).toBeVisible();
    expect(
      screen.getByText("Release: Arrival.2016.1080p.BluRay"),
    ).toBeVisible();
    expect(screen.getByText("Destination: movies")).toBeVisible();
    expect(
      screen.getByText(
        "The request may still be accepted; manual reconciliation may be required.",
      ),
    ).toBeVisible();
    expect(
      screen.queryByText(/history|progress|reconcile/i),
    ).not.toBeInTheDocument();
  });
});
