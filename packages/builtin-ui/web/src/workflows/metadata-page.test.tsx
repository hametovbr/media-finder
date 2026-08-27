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

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(appRoutes, { initialEntries: ["/add"] });
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

describe("MetadataPage", () => {
  it("groups provider-scoped results and requires explicit selection before saving", async () => {
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
    expect(
      within(await screen.findByRole("group", { name: "tmdb" })).getByText(
        /Arrival/,
      ),
    ).toBeVisible();
    expect(
      within(screen.getByRole("group", { name: "omdb" })).getByText(/Arrival/),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Save to catalog" }),
    ).toBeDisabled();

    await user.click(screen.getByRole("radio", { name: /tmdb.*Arrival/i }));
    await user.click(screen.getByRole("button", { name: "Save to catalog" }));

    expect(selectionBody).toEqual({ confirm_similarity: false });
    expect(await screen.findByText("Saved to catalog")).toBeVisible();
    expect(screen.getByRole("link", { name: "Find release" })).toHaveAttribute(
      "href",
      `/items/${mediaDetail.id}/releases`,
    );
  });

  it("confirms similarity explicitly and recovers safely from an expired selection", async () => {
    useBaseHandlers();
    let attempt = 0;
    server.use(
      http.post(
        `${baseUrl}/v1/metadata-selections/:token`,
        async ({ request }) => {
          attempt += 1;
          const body = (await request.json()) as {
            confirm_similarity?: boolean;
          };
          if (attempt === 1) {
            expect(body.confirm_similarity).toBe(false);
            return HttpResponse.json(
              {
                error: {
                  code: "confirmation_required",
                  request_id: "confirm-1",
                },
              },
              { status: 409 },
            );
          }
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
    await user.click(
      await screen.findByRole("radio", { name: /tmdb.*Arrival/i }),
    );
    await user.click(screen.getByRole("button", { name: "Save to catalog" }));

    expect(
      await screen.findByRole("dialog", { name: "Confirm similar title" }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Confirm selection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The selection expired. Search again.",
    );
    expect(
      screen.queryByRole("radio", { name: /Arrival/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Title" })).toBeVisible();
  });
});
