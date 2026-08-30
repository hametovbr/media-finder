import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ControlClient } from "./api/control-client";
import { ControlProvider } from "./api/control-provider";
import { appRoutes } from "./app-router";
import { createUiI18n } from "./i18n";
import {
  manualSeriesDetail,
  mediaDetail,
  metadataProviders,
  metadataResults,
} from "./mocks/fixtures";

async function expectNoSeriousViolations() {
  const result = await axe.run(document, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(
    result.violations.filter(
      ({ impact }) => impact === "critical" || impact === "serious",
    ),
  ).toEqual([]);
}

describe("accessibility", () => {
  it("has no serious axe violations in the catalog shell", async () => {
    const client = {
      bootstrapSession: vi.fn().mockResolvedValue({
        csrf_token: "axe-csrf",
        metadata_locale: "en",
        supported_locales: ["en", "ru"],
        ui_locale: "en",
      }),
      listCatalog: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
      listCollections: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
    } as unknown as ControlClient;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const router = createMemoryRouter(appRoutes, { initialEntries: ["/"] });

    render(
      <I18nextProvider i18n={createUiI18n("en")}>
        <QueryClientProvider client={queryClient}>
          <MantineProvider>
            <ControlProvider client={client}>
              <RouterProvider router={router} />
            </ControlProvider>
          </MantineProvider>
        </QueryClientProvider>
      </I18nextProvider>,
    );
    await screen.findByRole("heading", { name: "Catalog" });

    await expectNoSeriousViolations();
  });

  for (const locale of ["en", "ru"] as const) {
    it(`has no serious axe violations in the Manual editor (${locale})`, async () => {
      const client = {
        bootstrapSession: vi.fn().mockResolvedValue({
          csrf_token: "axe-csrf",
          metadata_locale: locale,
          supported_locales: ["en", "ru"],
          ui_locale: locale,
        }),
        getMediaItem: vi.fn().mockResolvedValue(manualSeriesDetail),
        listCollections: vi
          .fn()
          .mockResolvedValue({ items: [], next_cursor: null }),
      } as unknown as ControlClient;
      const router = createMemoryRouter(appRoutes, {
        initialEntries: [`/items/${manualSeriesDetail.id}/edit`],
      });
      render(
        <I18nextProvider i18n={createUiI18n(locale)}>
          <QueryClientProvider
            client={
              new QueryClient({ defaultOptions: { queries: { retry: false } } })
            }
          >
            <MantineProvider>
              <ControlProvider client={client}>
                <RouterProvider router={router} />
              </ControlProvider>
            </MantineProvider>
          </QueryClientProvider>
        </I18nextProvider>,
      );
      await screen.findByLabelText(
        locale === "en"
          ? "External ID"
          : "\u0412\u043d\u0435\u0448\u043d\u0438\u0439 ID",
      );
      await expectNoSeriousViolations();
    });

    it(`keeps metadata result selection keyboard-operable and accessible (${locale})`, async () => {
      const selectMetadata = vi.fn().mockResolvedValue(mediaDetail);
      const client = {
        bootstrapSession: vi.fn().mockResolvedValue({
          csrf_token: "axe-csrf",
          metadata_locale: locale,
          supported_locales: ["en", "ru"],
          ui_locale: locale,
        }),
        listMetadataProviders: vi.fn().mockResolvedValue(metadataProviders),
        searchMetadata: vi.fn().mockResolvedValue(
          metadataResults.map((result) => ({
            ...result,
            locale,
          })),
        ),
        selectMetadata,
      } as unknown as ControlClient;
      const router = createMemoryRouter(appRoutes, {
        initialEntries: ["/add"],
      });
      render(
        <I18nextProvider i18n={createUiI18n(locale)}>
          <QueryClientProvider
            client={
              new QueryClient({ defaultOptions: { queries: { retry: false } } })
            }
          >
            <MantineProvider>
              <ControlProvider client={client}>
                <RouterProvider router={router} />
              </ControlProvider>
            </MantineProvider>
          </QueryClientProvider>
        </I18nextProvider>,
      );
      const user = userEvent.setup();
      await user.click(
        await screen.findByRole("button", {
          name:
            locale === "en"
              ? "Search metadata providers"
              : "\u041d\u0430\u0439\u0442\u0438 \u0443 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u043e\u0432 \u043c\u0435\u0442\u0430\u0434\u0430\u043d\u043d\u044b\u0445",
        }),
      );
      await user.type(
        await screen.findByRole("searchbox", {
          name:
            locale === "en"
              ? "Title"
              : "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435",
        }),
        "Arrival",
      );
      await user.click(
        screen.getByRole("button", {
          name: locale === "en" ? "Search" : "\u041d\u0430\u0439\u0442\u0438",
        }),
      );
      const select = await screen.findAllByRole("button", {
        name:
          locale === "en"
            ? "Select"
            : "\u0412\u044b\u0431\u0440\u0430\u0442\u044c",
      });
      const firstSelect = select[0];
      if (firstSelect === undefined) throw new Error("metadata_select_missing");

      await expectNoSeriousViolations();
      firstSelect.focus();
      expect(firstSelect).toHaveFocus();
      await user.keyboard("{Enter}");

      expect(selectMetadata).toHaveBeenCalledTimes(1);
      expect(selectMetadata).toHaveBeenCalledWith("metadata-token-tmdb", false);
      expect(
        await screen.findByRole("heading", {
          name:
            locale === "en"
              ? "Saved to catalog"
              : "\u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u043e \u0432 \u043a\u0430\u0442\u0430\u043b\u043e\u0433",
        }),
      ).toBeVisible();
    });
  }
});
