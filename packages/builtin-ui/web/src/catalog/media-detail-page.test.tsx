import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { HttpResponse, delay, http } from "msw";
import { setupServer } from "msw/node";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { createControlClient } from "../api/control-client";
import { ControlProvider } from "../api/control-provider";
import { appRoutes } from "../app-router";
import { createUiI18n } from "../i18n";
import { manualSeriesDetail, mediaDetail, sessions } from "../mocks/fixtures";

const baseUrl = "http://localhost/api/control";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderDetail(itemId = mediaDetail.id) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(appRoutes, {
    initialEntries: [`/items/${itemId}`],
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

describe("MediaDetailPage", () => {
  it("shows rich normalized metadata and the first poster without rewriting it", async () => {
    useSession();
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, () =>
        HttpResponse.json(mediaDetail),
      ),
    );
    renderDetail();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Arrival" }),
    ).toBeVisible();
    expect(screen.getByText(mediaDetail.metadata.plot!)).toBeVisible();
    expect(screen.getByText("2016")).toBeVisible();
    expect(screen.getByText("Original title")).toBeVisible();
    expect(screen.getAllByText("Arrival")).toHaveLength(2);
    expect(screen.getByText("Genres")).toBeVisible();
    expect(
      screen
        .getAllByText(/^(Science Fiction|Drama)$/)
        .map((element) => element.textContent),
    ).toEqual(["Science Fiction", "Drama"]);
    const poster = screen.getByRole("img", { name: "Poster for Arrival" });
    expect(poster).toHaveAttribute(
      "src",
      "http://127.0.0.1:8080/manual-poster.jpg",
    );
    expect(poster).toHaveAttribute("loading", "lazy");
    expect(poster).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(screen.getByRole("link", { name: "Find release" })).toHaveAttribute(
      "href",
      `/items/${mediaDetail.id}/releases`,
    );
    expect(
      screen.queryByText(/season|episode|acquisition history/i),
    ).not.toBeInTheDocument();
  });

  it("omits whitespace-only metadata and keeps actions beside the local poster fallback", async () => {
    useSession();
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, () =>
        HttpResponse.json({
          ...mediaDetail,
          id: "empty-detail",
          metadata: {
            ...mediaDetail.metadata,
            artwork: [],
            genres: [" ", ""],
            original_title: "   ",
            plot: null,
            titles: { en: "Empty detail" },
            year: null,
          },
        }),
      ),
    );
    renderDetail("empty-detail");

    expect(
      await screen.findByRole("img", {
        name: "Poster unavailable for Empty detail",
      }),
    ).toBeVisible();
    expect(screen.queryByText("Original title")).not.toBeInTheDocument();
    expect(screen.queryByText("Genres")).not.toBeInTheDocument();
    expect(screen.queryByText("2016")).not.toBeInTheDocument();
    expect(
      screen.getByText("No overview is available for this item."),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Find release" })).toBeVisible();
  });

  it("replaces a failed poster locally and resets failure for a new item URL", async () => {
    useSession();
    const secondDetail = {
      ...mediaDetail,
      external_id: "second",
      id: "second-detail",
      metadata: {
        ...mediaDetail.metadata,
        artwork: [
          {
            kind: "poster",
            url: "https://images.example.invalid/posters/second.jpg",
          },
        ],
        original_title: "Second original",
        titles: { en: "Second detail" },
      },
    };
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, ({ params }) =>
        HttpResponse.json(
          params.itemId === secondDetail.id ? secondDetail : mediaDetail,
        ),
      ),
    );
    const router = renderDetail();

    fireEvent.error(
      await screen.findByRole("img", { name: "Poster for Arrival" }),
    );
    expect(
      screen.getByRole("img", { name: "Poster unavailable for Arrival" }),
    ).toBeVisible();
    expect(screen.getByText(mediaDetail.metadata.plot!)).toBeVisible();
    expect(screen.getByRole("link", { name: "Find release" })).toBeVisible();

    await router.navigate(`/items/${secondDetail.id}`);
    expect(
      await screen.findByRole("img", { name: "Poster for Second detail" }),
    ).toHaveAttribute(
      "src",
      "https://images.example.invalid/posters/second.jpg",
    );
  });

  it("does not expose season or episode hierarchy for a normalized series", async () => {
    useSession();
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, () =>
        HttpResponse.json({
          ...mediaDetail,
          id: "dark-2017",
          kind: "series",
          metadata: {
            ...mediaDetail.metadata,
            kind: "series",
            titles: { en: "Dark", ru: "\u0422\u044c\u043c\u0430" },
            seasons: [{ episodes: [], number: 1, title: "Season One" }],
          },
        }),
      ),
    );
    renderDetail("dark-2017");

    expect(await screen.findByRole("heading", { name: "Dark" })).toBeVisible();
    expect(screen.queryByText("Season One")).not.toBeInTheDocument();
  });

  it("exposes Manual edit only for Manual items", async () => {
    useSession();
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, ({ params }) =>
        HttpResponse.json(
          params.itemId === manualSeriesDetail.id
            ? manualSeriesDetail
            : mediaDetail,
        ),
      ),
    );
    renderDetail(manualSeriesDetail.id);

    expect(
      await screen.findByRole("link", { name: "Edit Manual metadata" }),
    ).toHaveAttribute("href", `/items/${manualSeriesDetail.id}/edit`);

    renderDetail(mediaDetail.id);
    expect(
      await screen.findByRole("heading", { name: "Arrival" }),
    ).toBeVisible();
    expect(
      screen.getAllByRole("link", { name: "Edit Manual metadata" }),
    ).toHaveLength(1);
  });

  it("renders localized loading and safe missing-item feedback", async () => {
    useSession();
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, async () => {
        await delay(200);
        return HttpResponse.json(
          {
            error: {
              code: "media_item_not_found",
              request_id: "request-missing",
            },
          },
          { status: 404 },
        );
      }),
    );
    renderDetail("missing");

    expect(await screen.findByLabelText("Loading media item")).toBeVisible();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The requested media item was not found.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("request-missing");
  });

  it("retains the safe metadata-unavailable response", async () => {
    useSession();
    server.use(
      http.get(`${baseUrl}/v1/media-items/:itemId`, () =>
        HttpResponse.json(
          {
            error: {
              code: "metadata_unavailable",
              request_id: "request-purged",
            },
          },
          { status: 410 },
        ),
      ),
    );
    renderDetail("purged");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Metadata for this item is no longer available.",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("request-purged");
  });
});
