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
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { ControlFailure, type ControlClient } from "./api/control-client";
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

async function renderRoute(path: string, locale: "en" | "ru" = "en") {
  const client = {
    bootstrapSession: vi
      .fn()
      .mockResolvedValue({ ...session, ui_locale: locale }),
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
  return { client, i18n, queryClient, router };
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

describe("interface language recovery", () => {
  it.each(["en", "ru"] as const)(
    "retains confirmed %s language and form state after failure, then retries only the failed locale",
    async (locale) => {
      const user = userEvent.setup();
      const { client, i18n, router } = await renderRoute("/add/manual", locale);
      await waitFor(() => expect(i18n.resolvedLanguage).toBe(locale));
      const target = locale === "en" ? "ru" : "en";
      const title = screen.getByLabelText(
        i18n.t("manual.fields.title", { locale: i18n.t("manual.locales.en") }),
      );
      await user.type(title, "Retained title");
      vi.mocked(client.updateSession).mockRejectedValueOnce(
        new ControlFailure(
          "unrecognized_code",
          503,
          "request-test",
          "DO-NOT-DISPLAY",
        ),
      );
      await user.click(
        screen.getByRole("button", {
          name:
            target === "ru"
              ? "\u0420\u0443\u0441\u0441\u043a\u0438\u0439"
              : "English",
        }),
      );
      expect(await screen.findByRole("alert")).toHaveTextContent(
        i18n.t("errors.unexpected_response"),
      );
      expect(screen.queryByText(/DO-NOT-DISPLAY/)).not.toBeInTheDocument();
      expect(i18n.resolvedLanguage).toBe(locale);
      expect(document.documentElement.lang).toBe(locale);
      expect(title).toHaveValue("Retained title");
      expect(router.state.location.pathname).toBe("/add/manual");
      let resolveUpdate!: (
        value: Awaited<ReturnType<ControlClient["updateSession"]>>,
      ) => void;
      vi.mocked(client.updateSession).mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveUpdate = resolve;
          }),
      );
      const retry = screen.getByRole("button", {
        name: i18n.t("recovery.retry"),
      });
      retry.focus();
      act(() => {
        fireEvent.click(retry);
        fireEvent.click(retry);
      });
      await waitFor(() =>
        expect(client.updateSession).toHaveBeenCalledTimes(2),
      );
      expect(retry).toBeDisabled();
      expect(screen.getByRole("status")).toHaveTextContent(
        i18n.t("locale.updating"),
      );
      await act(async () => {
        resolveUpdate({
          ...session,
          supported_locales: ["en", "ru"],
          ui_locale: target,
        });
      });
      await waitFor(() => expect(document.documentElement.lang).toBe(target));
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(
        screen.getByRole("button", {
          name:
            target === "ru"
              ? "English"
              : "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
        }),
      ).toHaveFocus();
      expect(title).toHaveValue("Retained title");
      expect(router.state.location.pathname).toBe("/add/manual");
      expect(client.updateSession).toHaveBeenNthCalledWith(2, {
        ui_locale: target,
      });
      expect(client.bootstrapSession).toHaveBeenCalledTimes(1);
      expect(client.searchMetadata).not.toHaveBeenCalled();
    },
  );

  it("does not steal input focus when a delayed language failure arrives", async () => {
    const user = userEvent.setup();
    const { client } = await renderRoute("/add/manual");
    let rejectUpdate!: (reason: Error) => void;
    vi.mocked(client.updateSession).mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectUpdate = reject;
        }),
    );
    await user.click(
      screen.getByRole("button", {
        name: "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
      }),
    );
    const title = screen.getByLabelText("Title (English)");
    await user.click(title);
    await act(async () => rejectUpdate(new Error("private network detail")));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The server returned an unexpected response.",
    );
    expect(title).toHaveFocus();
    expect(
      screen.queryByText("private network detail"),
    ).not.toBeInTheDocument();
  });
});

it("keeps typing focus when locale retry finishes refreshing page queries", async () => {
  const user = userEvent.setup();
  const { client, queryClient, i18n } = await renderRoute("/add/manual");
  vi.mocked(client.updateSession).mockRejectedValueOnce(new Error("offline"));
  await user.click(
    screen.getByRole("button", {
      name: "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
    }),
  );
  const retry = await screen.findByRole("button", { name: "Retry" });
  let finishRefresh!: () => void;
  vi.spyOn(queryClient, "invalidateQueries").mockImplementationOnce(
    () =>
      new Promise<void>((resolve) => {
        finishRefresh = resolve;
      }),
  );
  await user.click(retry);
  await waitFor(() => expect(document.documentElement.lang).toBe("ru"));
  const title = screen.getByLabelText(
    i18n.t("manual.fields.title", { locale: i18n.t("manual.locales.en") }),
  );
  await user.click(title);
  await act(async () => finishRefresh());
  expect(title).toHaveFocus();
});
