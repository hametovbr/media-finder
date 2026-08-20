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

    const result = await axe.run(document, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(
      result.violations.filter(
        ({ impact }) => impact === "critical" || impact === "serious",
      ),
    ).toEqual([]);
  });
});
