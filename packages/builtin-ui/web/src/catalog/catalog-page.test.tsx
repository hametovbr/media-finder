import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
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
import { catalogItems, collections, sessions } from "../mocks/fixtures";

const baseUrl = "http://localhost/api/control";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderCatalog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(appRoutes, { initialEntries: ["/"] });
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
}

function useSessionHandler() {
  server.use(
    http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
  );
}

describe("CatalogPage", () => {
  it("renders informative cards and a stable local artwork fallback", async () => {
    useSessionHandler();
    server.use(
      http.get(`${baseUrl}/v1/collections`, () =>
        HttpResponse.json({ items: collections, next_cursor: null }),
      ),
      http.get(`${baseUrl}/v1/media-items`, () =>
        HttpResponse.json({ items: catalogItems, next_cursor: null }),
      ),
    );

    renderCatalog();

    const arrival = await screen.findByRole("article", { name: "Arrival" });
    expect(within(arrival).getByText("2016")).toBeInTheDocument();
    expect(within(arrival).getByText("Movie")).toBeInTheDocument();
    expect(within(arrival).getByText("tmdb")).toBeInTheDocument();
    expect(within(arrival).getByText("Submitted")).toBeInTheDocument();
    expect(
      within(arrival).getByTestId("poster-placeholder"),
    ).toBeInTheDocument();

    const pending = screen.getByRole("article", { name: "Dark" });
    expect(
      within(pending).getByText("Pending — may require manual reconciliation"),
    ).toBeVisible();
    expect(screen.queryByText(/download progress/i)).not.toBeInTheDocument();
  });

  it("filters through read-only collections and Uncategorized", async () => {
    const requestedQueries: URLSearchParams[] = [];
    useSessionHandler();
    server.use(
      http.get(`${baseUrl}/v1/collections`, () =>
        HttpResponse.json({ items: collections, next_cursor: null }),
      ),
      http.get(`${baseUrl}/v1/media-items`, ({ request }) => {
        requestedQueries.push(new URL(request.url).searchParams);
        return HttpResponse.json({ items: catalogItems, next_cursor: null });
      }),
    );
    const user = userEvent.setup();
    renderCatalog();

    await screen.findByRole("article", { name: "Arrival" });
    await user.click(screen.getByRole("button", { name: "Favorites" }));
    await user.click(screen.getByRole("button", { name: "Uncategorized" }));

    expect(
      requestedQueries.some(
        (query) => query.get("collection_id") === "favorites",
      ),
    ).toBe(true);
    expect(
      requestedQueries.some((query) => query.get("uncategorized") === "true"),
    ).toBe(true);
    expect(
      requestedQueries.every((query) => query.get("archived") === "false"),
    ).toBe(true);
  });

  it("loads the next catalog cursor without replacing existing cards", async () => {
    useSessionHandler();
    server.use(
      http.get(`${baseUrl}/v1/collections`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(`${baseUrl}/v1/media-items`, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        return cursor === "page-2"
          ? HttpResponse.json({ items: [catalogItems[1]], next_cursor: null })
          : HttpResponse.json({
              items: [catalogItems[0]],
              next_cursor: "page-2",
            });
      }),
    );
    const user = userEvent.setup();
    renderCatalog();

    await screen.findByRole("article", { name: "Arrival" });
    await user.click(screen.getByRole("button", { name: "Load more" }));

    expect(await screen.findByRole("article", { name: "Dark" })).toBeVisible();
    expect(screen.getByRole("article", { name: "Arrival" })).toBeVisible();
  });
});
