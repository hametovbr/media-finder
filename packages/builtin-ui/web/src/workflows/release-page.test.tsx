import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
}

function useSession() {
  server.use(
    http.get(`${baseUrl}/v1/session`, () => HttpResponse.json(sessions.en)),
  );
}

describe("ReleasePage", () => {
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
});
