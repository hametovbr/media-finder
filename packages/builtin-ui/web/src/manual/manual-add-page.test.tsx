import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitForElementToBeRemoved,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { ControlFailure, type ControlClient } from "../api/control-client";
import type { components } from "../api/control.generated";
import { ControlProvider } from "../api/control-provider";
import { appRoutes } from "../app-router";
import { createUiI18n } from "../i18n";

type ManualDocument = components["schemas"]["ManualDocumentV1"];
type ManualImportRequest = components["schemas"]["ManualImportRequest"];
type MediaItem = components["schemas"]["MediaItemDetail"];

const session = {
  csrf_token: "manual-csrf",
  metadata_locale: "en" as const,
  supported_locales: ["en", "ru"] as const,
  ui_locale: "en" as const,
};

function itemFromDocument(document: ManualDocument): MediaItem {
  const {
    external_id: requestedIdentity,
    locale,
    schema_version,
    ...metadata
  } = document;
  void locale;
  void schema_version;
  return {
    acquisitions: [],
    archived: false,
    collection_id: null,
    external_id: requestedIdentity ?? "5ab363a4-6735-4a73-a2d8-8ca67acb7942",
    id: `saved-${document.kind}`,
    kind: document.kind,
    metadata,
    provider_key: "manual",
  };
}

async function renderManualAdd(options?: {
  confirmManual?: (token: string) => Promise<MediaItem>;
  importManual?: (request: ManualImportRequest) => Promise<MediaItem>;
}) {
  let savedItem: MediaItem | null = null;
  const importManual = vi.fn(async (request: ManualImportRequest) => {
    if (options?.importManual) return options.importManual(request);
    const { document } = request;
    savedItem = itemFromDocument(document);
    return savedItem;
  });
  const client = {
    bootstrapSession: vi.fn().mockResolvedValue(session),
    confirmManual: vi.fn(async (token: string) => {
      if (options?.confirmManual) return options.confirmManual(token);
      if (!savedItem) throw new Error("missing saved item");
      return savedItem;
    }),
    getMediaItem: vi.fn(async () => savedItem),
    importManual,
    listCollections: vi.fn().mockResolvedValue({
      items: [{ archived: false, id: "favorites", name: "Favorites" }],
      next_cursor: null,
    }),
    searchReleases: vi.fn(),
    submitAcquisition: vi.fn(),
  } as unknown as ControlClient;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(appRoutes, {
    initialEntries: ["/add/manual"],
  });
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
  await screen.findByRole("heading", { name: "Manual metadata" });
  return { client, importManual, router };
}

describe("ManualAddPage", () => {
  it("creates a structured movie in an optional collection and opens its detail", async () => {
    const user = userEvent.setup();
    const { client, importManual, router } = await renderManualAdd();

    await user.type(
      await screen.findByLabelText("Title (English)"),
      "New movie",
    );
    const collection = screen.getByRole("combobox", { name: "Collection" });
    await user.click(collection);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(collection).toHaveValue("Favorites");
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );

    expect(
      await screen.findByRole("heading", { name: "New movie" }),
    ).toBeVisible();
    expect(router.state.location.pathname).toBe("/items/saved-movie");
    expect(importManual).toHaveBeenCalledWith({
      collection_id: "favorites",
      document: expect.objectContaining({
        kind: "movie",
        locale: "en",
        schema_version: "1",
        titles: { en: "New movie" },
      }),
    });
    expect(client.searchReleases).not.toHaveBeenCalled();
    expect(client.submitAcquisition).not.toHaveBeenCalled();
  });

  it("creates a structured series with Season 00 and a regular season", async () => {
    const user = userEvent.setup();
    const { client, importManual, router } = await renderManualAdd();

    const mediaKind = await screen.findByRole("combobox", {
      name: "Media kind",
    });
    await user.click(mediaKind);
    await user.keyboard("{ArrowDown}{Enter}");
    expect(mediaKind).toHaveValue("Series");
    await user.type(screen.getByLabelText("Title (English)"), "New series");

    await user.click(screen.getByRole("button", { name: "Add season" }));
    const firstSeason = screen.getByRole("group", { name: "Season 1" });
    await user.clear(within(firstSeason).getByLabelText("Season number"));
    await user.type(within(firstSeason).getByLabelText("Season number"), "0");
    const specials = await screen.findByRole("group", { name: "Season 0" });
    await user.click(
      within(specials).getByRole("button", { name: "Add episode" }),
    );
    await user.type(
      within(specials).getByLabelText("Episode title"),
      "Special",
    );

    await user.click(screen.getByRole("button", { name: "Add season" }));
    const regular = screen.getByRole("group", { name: "Season 1" });
    await user.click(
      within(regular).getByRole("button", { name: "Add episode" }),
    );
    await user.type(within(regular).getByLabelText("Episode title"), "Pilot");
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );

    expect(
      await screen.findByRole("heading", { name: "New series" }),
    ).toBeVisible();
    expect(router.state.location.pathname).toBe("/items/saved-series");
    expect(importManual).toHaveBeenCalledWith({
      collection_id: null,
      document: expect.objectContaining({
        kind: "series",
        seasons: [
          expect.objectContaining({
            episodes: [expect.objectContaining({ title: "Special" })],
            number: 0,
          }),
          expect.objectContaining({
            episodes: [expect.objectContaining({ title: "Pilot" })],
            number: 1,
          }),
        ],
      }),
    });
    expect(client.searchReleases).not.toHaveBeenCalled();
    expect(client.submitAcquisition).not.toHaveBeenCalled();
  }, 10_000);

  it("imports pasted complete version-1 JSON without rewriting rich fields", async () => {
    const user = userEvent.setup();
    const { importManual, router } = await renderManualAdd();
    const document: ManualDocument = {
      artwork: [
        {
          kind: "poster",
          language: "ru",
          url: "https://images.example/manual-poster.jpg",
        },
      ],
      countries: ["RU"],
      external_id: "manual-existing-rich",
      genres: ["Drama"],
      kind: "series",
      locale: "ru",
      original_title: "Original title",
      people: [{ character: "Lead", name: "Actor", role: "cast" }],
      plot: "Rich plot",
      provider_ids: { legacy: "preserved" },
      ratings: [{ source: "manual", value: 8.5, votes: 12 }],
      release_date: "2026-08-27",
      runtime_minutes: 50,
      schema_version: "1",
      seasons: [
        {
          episodes: [
            {
              number: 1,
              provider_ids: { legacy_episode: "one" },
              title: "Special",
            },
          ],
          number: 0,
          provider_ids: { legacy_season: "zero" },
          title: "Specials",
        },
      ],
      studios: ["Studio"],
      tags: ["Imported"],
      titles: {
        en: "Rich series",
        ru: "\u041f\u043e\u043b\u043d\u044b\u0439 \u0441\u0435\u0440\u0438\u0430\u043b",
      },
      year: 2026,
    };

    await user.click(
      await screen.findByRole("button", { name: "Complete JSON" }),
    );
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: JSON.stringify(document) },
    });
    await user.click(
      screen.getByRole("button", { name: "Import Manual JSON" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Rich series" }),
    ).toBeVisible();
    expect(router.state.location.pathname).toBe("/items/saved-series");
    expect(importManual).toHaveBeenCalledWith({
      collection_id: null,
      document,
    });
  });

  it("loads JSON from a local file and reports bounded client shape errors", async () => {
    const user = userEvent.setup();
    const { importManual } = await renderManualAdd();

    await user.click(
      await screen.findByRole("button", { name: "Complete JSON" }),
    );
    const input =
      document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    await user.upload(
      input!,
      new File(["[]"], "manual.json", { type: "application/json" }),
    );
    expect(screen.getByLabelText("Manual JSON")).toHaveValue("[]");
    await user.click(
      screen.getByRole("button", { name: "Import Manual JSON" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The JSON document must be an object.",
    );

    await user.clear(screen.getByLabelText("Manual JSON"));
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: "not json" },
    });
    await user.click(
      screen.getByRole("button", { name: "Import Manual JSON" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Enter valid JSON.");

    await user.clear(screen.getByLabelText("Manual JSON"));
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: JSON.stringify({ schema_version: "2" }) },
    });
    await user.click(
      screen.getByRole("button", { name: "Import Manual JSON" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The document must use schema version 1.",
    );
    expect(importManual).not.toHaveBeenCalled();
  });

  it("leaves semantic validation to the server and renders only its safe invariant", async () => {
    const user = userEvent.setup();
    const importManual = vi.fn(async () => {
      throw new ControlFailure("request_body_invalid", 422, "request-safe");
    });
    await renderManualAdd({ importManual });
    const document = {
      artwork: [],
      countries: [],
      genres: [],
      kind: "movie",
      locale: "en",
      people: [],
      ratings: [],
      schema_version: "1",
      seasons: [],
      studios: [],
      tags: [],
      titles: {},
    } as const;

    await user.click(
      await screen.findByRole("button", { name: "Complete JSON" }),
    );
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: JSON.stringify(document) },
    });
    await user.click(
      screen.getByRole("button", { name: "Import Manual JSON" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The request data is invalid.",
    );
    expect(screen.queryByText("request-safe")).not.toBeInTheDocument();
    expect(importManual).toHaveBeenCalledWith({
      collection_id: null,
      document,
    });
  });

  it("requires explicit confirmation, supports cancellation, and keeps the token ephemeral", async () => {
    const user = userEvent.setup();
    const token = "opaque-manual-token-never-render";
    const importManual = vi.fn(async () => {
      throw new ControlFailure("confirmation_required", 409, null, token);
    });
    const { client, router } = await renderManualAdd({ importManual });

    await user.type(
      await screen.findByLabelText("Title (English)"),
      "Duplicate",
    );
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    expect(
      await screen.findByRole("dialog", { name: "Confirm Manual revision" }),
    ).toBeVisible();
    expect(document.body).not.toHaveTextContent(token);
    expect(router.state.location.pathname).toBe("/add/manual");
    expect(router.state.location.search).toBe("");
    expect(localStorage.getItem(token)).toBeNull();
    expect(sessionStorage.getItem(token)).toBeNull();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitForElementToBeRemoved(() =>
      screen.queryByRole("dialog", { name: "Confirm Manual revision" }),
    );
    expect(screen.getByLabelText("Title (English)")).toHaveValue("Duplicate");
    expect(client.confirmManual).not.toHaveBeenCalled();
  });

  it("confirms a duplicate exactly once and opens the resulting item", async () => {
    const user = userEvent.setup();
    const token = "opaque-confirm-once";
    const document = createManualDocumentFixture("Confirmed duplicate");
    const savedItem = itemFromDocument(document);
    const importManual = vi.fn(async () => {
      throw new ControlFailure("confirmation_required", 409, null, token);
    });
    const confirmManual = vi.fn(async () => savedItem);
    const { client, router } = await renderManualAdd({
      confirmManual,
      importManual,
    });

    await user.click(
      await screen.findByRole("button", { name: "Complete JSON" }),
    );
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: JSON.stringify(document) },
    });
    await user.click(
      screen.getByRole("button", { name: "Import Manual JSON" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Confirm revision" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Confirmed duplicate" }),
    ).toBeVisible();
    expect(client.confirmManual).toHaveBeenCalledTimes(1);
    expect(client.confirmManual).toHaveBeenCalledWith(token);
    expect(router.state.location.pathname).toBe("/items/saved-movie");
  });

  it("clears an expired confirmation and requires a fresh originating request", async () => {
    const user = userEvent.setup();
    const token = "expired-opaque-token";
    const importManual = vi.fn(async () => {
      throw new ControlFailure("confirmation_required", 409, null, token);
    });
    const confirmManual = vi.fn(async () => {
      throw new ControlFailure("selection_expired", 410);
    });
    const { client } = await renderManualAdd({ confirmManual, importManual });

    await user.type(
      await screen.findByLabelText("Title (English)"),
      "Retained",
    );
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Confirm revision" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The selection expired. Submit the Manual document again.",
    );
    await waitForElementToBeRemoved(() =>
      screen.queryByRole("dialog", { name: "Confirm Manual revision" }),
    );
    expect(screen.getByLabelText("Title (English)")).toHaveValue("Retained");
    expect(importManual).toHaveBeenCalledTimes(1);
    expect(client.confirmManual).toHaveBeenCalledTimes(1);
  });
});

function createManualDocumentFixture(title: string): ManualDocument {
  return {
    artwork: [],
    countries: [],
    genres: [],
    kind: "movie",
    locale: "en",
    people: [],
    ratings: [],
    schema_version: "1",
    seasons: [],
    studios: [],
    tags: [],
    titles: { en: title },
  };
}
