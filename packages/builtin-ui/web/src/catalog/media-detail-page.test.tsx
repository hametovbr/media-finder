import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { HttpResponse, delay, http } from "msw";
import { setupServer } from "msw/node";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { createControlClient } from "../api/control-client";
import { ControlProvider } from "../api/control-provider";
import { appRoutes } from "../app-router";
import { createUiI18n } from "../i18n";
import { mediaDetail, sessions } from "../mocks/fixtures";

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
}

function useSession() {
  server.use(
    http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
  );
}

describe("MediaDetailPage", () => {
  it("shows a normalized movie overview and Find release without omitted claims", async () => {
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
    expect(screen.getByRole("link", { name: "Find release" })).toHaveAttribute(
      "href",
      `/items/${mediaDetail.id}/releases`,
    );
    expect(
      screen.queryByText(/season|episode|acquisition history/i),
    ).not.toBeInTheDocument();
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
});
