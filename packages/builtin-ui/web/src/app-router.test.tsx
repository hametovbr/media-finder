import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ControlClient } from "./api/control-client";
import { ControlProvider } from "./api/control-provider";
import { appRoutes } from "./app-router";
import { createUiI18n } from "./i18n";
import { mediaDetail } from "./mocks/fixtures";

const session = {
  csrf_token: "csrf-test-token",
  metadata_locale: "en" as const,
  supported_locales: ["en", "ru"] as const,
  ui_locale: "en" as const,
};

async function renderRoute(path: string) {
  const client = {
    bootstrapSession: vi.fn().mockResolvedValue(session),
    getMediaItem: vi.fn().mockResolvedValue({
      ...mediaDetail,
      external_id: "item-42",
      id: "item-42",
      metadata: {
        ...mediaDetail.metadata,
        titles: { en: "Media overview" },
      },
      provider_key: "fixture",
    }),
    listCatalog: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listCollections: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listMetadataProviders: vi.fn().mockResolvedValue([]),
    searchMetadata: vi.fn().mockResolvedValue([]),
    listDownloadDestinations: vi.fn().mockResolvedValue([]),
    updateSession: vi.fn().mockImplementation(async ({ ui_locale }) => ({
      ...session,
      ui_locale: ui_locale ?? session.ui_locale,
    })),
  } as unknown as ControlClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const i18n = createUiI18n("en");
  const router = createMemoryRouter(appRoutes, { initialEntries: [path] });
  render(
    <I18nextProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <MantineProvider>
          <ControlProvider client={client} loadingFallback={<p>loading</p>}>
            <RouterProvider router={router} />
          </ControlProvider>
        </MantineProvider>
      </QueryClientProvider>
    </I18nextProvider>,
  );
  await screen.findByRole("banner");
  return { client, i18n, queryClient };
}

describe("application routes", () => {
  it.each([
    ["/", "Catalog"],
    ["/add", "Add title"],
    ["/add/manual", "Manual metadata"],
    ["/items/item-42", "Media overview"],
    ["/items/item-42/releases", "Find release"],
  ])("renders the supported bookmark %s", async (path, heading) => {
    await renderRoute(path);
    expect(
      await screen.findByRole("heading", { level: 1, name: heading }),
    ).toBeInTheDocument();
  });

  it.each(["/settings", "/about"])(
    "renders localized not-found feedback for omitted route %s",
    async (path) => {
      await renderRoute(path);
      expect(
        screen.getByRole("heading", { name: "Page not found" }),
      ).toBeInTheDocument();
    },
  );

  it("requires an explicit provider or Manual choice without searching providers for Manual", async () => {
    const user = userEvent.setup();
    const { client } = await renderRoute("/add");

    expect(screen.queryByRole("searchbox")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Search metadata providers" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("link", { name: "Enter or import Manual metadata" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Manual metadata" }),
    ).toBeInTheDocument();
    expect(client.searchMetadata).not.toHaveBeenCalled();
  });

  it("keeps primary navigation visible and switches the session locale", async () => {
    const user = userEvent.setup();
    const { client, queryClient } = await renderRoute("/");
    queryClient.setQueryData(["control", "catalog", "en"], { items: [] });

    expect(
      screen.getByRole("navigation", { name: "Primary navigation" }),
    ).toBeVisible();
    await user.click(
      screen.getByRole("button", {
        name: "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
      }),
    );

    expect(client.updateSession).toHaveBeenCalledWith({ ui_locale: "ru" });
    expect(
      await screen.findByRole("heading", {
        name: "\u041a\u0430\u0442\u0430\u043b\u043e\u0433",
      }),
    ).toBeInTheDocument();
    expect(
      queryClient.getQueryState(["control", "catalog", "en"])?.isInvalidated,
    ).toBe(true);
  });

  it("moves focus to the main region after client-side navigation", async () => {
    const user = userEvent.setup();
    await renderRoute("/");

    await user.click(screen.getByRole("link", { name: "Add title" }));
    await screen.findByRole("heading", { name: "Add title" });

    expect(screen.getByRole("main")).toHaveFocus();
  });
});
