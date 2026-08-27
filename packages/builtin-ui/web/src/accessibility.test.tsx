import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import axe from "axe-core";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ControlClient } from "./api/control-client";
import { ControlProvider } from "./api/control-provider";
import { appRoutes } from "./app-router";
import { createUiI18n } from "./i18n";
import { manualSeriesDetail } from "./mocks/fixtures";

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
  }
});
