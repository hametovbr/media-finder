import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

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
  initialEntries?: string[];
  initialIndex?: number;
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
      const confirmed = options?.confirmManual
        ? await options.confirmManual(token)
        : savedItem;
      if (!confirmed) throw new Error("missing saved item");
      savedItem = confirmed;
      return confirmed;
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
    initialEntries: options?.initialEntries ?? ["/add/manual"],
    initialIndex: options?.initialIndex,
  });
  const view = render(
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
  return { client, importManual, queryClient, router, unmount: view.unmount };
}

describe("ManualAddPage", () => {
  it("reviews dirty structured, raw-list, collection, and JSON drafts but permits reverted drafts", async () => {
    const user = userEvent.setup();
    const clean = await renderManualAdd();
    const cleanTitle = await screen.findByLabelText("Title (English)");
    await user.type(cleanTitle, "Reverted");
    await user.clear(cleanTitle);
    void clean.router.navigate("/");
    await waitFor(() => expect(clean.router.state.location.pathname).toBe("/"));
    clean.unmount();

    const raw = await renderManualAdd();
    await screen.findByLabelText("Title (English)");
    await user.click(screen.getByRole("button", { name: "Additional fields" }));
    await user.type(screen.getByLabelText("Tags"), "draft");
    void raw.router.navigate("/");
    await waitFor(() =>
      expect(
        screen.getByRole("dialog", { name: "Unsaved changes" }),
      ).toBeVisible(),
    );
    await userEvent.setup().keyboard("{Enter}");
    raw.unmount();

    const collection = await renderManualAdd();
    const select = await screen.findByRole("combobox", { name: "Collection" });
    await user.click(select);
    await user.keyboard("{ArrowDown}{Enter}");
    void collection.router.navigate("/");
    await waitFor(() =>
      expect(
        screen.getByRole("dialog", { name: "Unsaved changes" }),
      ).toBeVisible(),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Stay" })).toHaveFocus(),
    );
    await userEvent.setup().keyboard("{Enter}");
    collection.unmount();

    const json = await renderManualAdd();
    await screen.findByLabelText("Title (English)");
    await user.click(screen.getByRole("button", { name: "Complete JSON" }));
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: "{}" },
    });
    void json.router.navigate("/");
    await waitFor(() =>
      expect(
        screen.getByRole("dialog", { name: "Unsaved changes" }),
      ).toBeVisible(),
    );
  });

  it("reviews browser back navigation and preserves the mode and draft on Stay", async () => {
    const user = userEvent.setup();
    const { router } = await renderManualAdd({
      initialEntries: ["/", "/add/manual"],
      initialIndex: 1,
    });
    await user.click(screen.getByRole("button", { name: "Complete JSON" }));
    fireEvent.change(await screen.findByLabelText("Manual JSON"), {
      target: { value: "{}" },
    });
    void router.navigate(-1);
    await waitFor(() =>
      expect(
        screen.getByRole("dialog", { name: "Unsaved changes" }),
      ).toBeVisible(),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Stay" })).toHaveFocus(),
    );
    await userEvent.setup().keyboard("{Enter}");
    await waitForElementToBeRemoved(
      screen.getByRole("dialog", { name: "Unsaved changes" }),
    );
    expect(router.state.location.pathname).toBe("/add/manual");
    expect(screen.getByLabelText("Manual JSON")).toHaveValue("{}");
  });

  it("installs the browser-unload guard only for a dirty add draft", async () => {
    const { unmount } = await renderManualAdd();
    const cleanEvent = new Event("beforeunload", { cancelable: true });
    globalThis.dispatchEvent(cleanEvent);
    expect(cleanEvent.defaultPrevented).toBe(false);

    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Draft" },
    });
    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    globalThis.dispatchEvent(dirtyEvent);
    expect(dirtyEvent.defaultPrevented).toBe(true);

    unmount();
    const removedEvent = new Event("beforeunload", { cancelable: true });
    globalThis.dispatchEvent(removedEvent);
    expect(removedEvent.defaultPrevented).toBe(false);
  });

  it("keeps a dirty add draft on Stay and discards it only after explicit leave", async () => {
    const { importManual, router } = await renderManualAdd();
    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Draft" },
    });
    const title = screen.getByLabelText("Title (English)");
    title.focus();
    void router.navigate("/");
    const dialog = await screen.findByRole("dialog", {
      name: "Unsaved changes",
    });
    await waitFor(() => expect(dialog).toBeVisible());
    expect(screen.getByRole("button", { name: "Stay" })).toHaveFocus();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Stay" })).toHaveFocus(),
    );
    await userEvent.setup().keyboard("{Enter}");
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Unsaved changes" }),
      ).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(title).toHaveFocus());
    expect(router.state.location.pathname).toBe("/add/manual");
    expect(screen.getByLabelText("Title (English)")).toHaveValue("Draft");
    expect(importManual).not.toHaveBeenCalled();

    void router.navigate("/");
    const leaveDialog = await screen.findByRole("dialog", {
      name: "Unsaved changes",
    });
    fireEvent.click(screen.getByRole("button", { name: "Discard and leave" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    expect(leaveDialog).not.toBeInTheDocument();
  });

  it("keeps mutations and navigation excluded until delayed completion finishes", async () => {
    const invalidation = deferred<void>();
    const saved = itemFromDocument(createManualDocumentFixture("Finished"));
    const { importManual, queryClient, router } = await renderManualAdd({
      importManual: async () => saved,
    });
    vi.spyOn(queryClient, "invalidateQueries").mockImplementation(
      () => invalidation.promise,
    );
    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Finished" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    await waitFor(() => expect(importManual).toHaveBeenCalledTimes(1));
    await router.navigate("/");

    expect(router.state.location.pathname).toBe("/add/manual");
    expect(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    ).toBeDisabled();
    fireEvent.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    expect(importManual).toHaveBeenCalledTimes(1);
    invalidation.resolve();
    expect(
      await screen.findByRole("heading", { name: "Finished" }),
    ).toBeVisible();
    expect(router.state.location.pathname).toBe("/items/saved-movie");
  });

  it("ignores save and JSON-read completion after the add page unmounts", async () => {
    const save = deferred<MediaItem>();
    const { importManual, router, unmount } = await renderManualAdd({
      importManual: () => save.promise,
    });
    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Abandoned" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    await waitFor(() => expect(importManual).toHaveBeenCalledTimes(1));
    unmount();
    save.resolve(itemFromDocument(createManualDocumentFixture("Abandoned")));
    await save.promise;
    expect(router.state.location.pathname).toBe("/add/manual");

    const read = deferred<string>();
    const rendered = await renderManualAdd();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Complete JSON" }));
    const file = new File(["ignored"], "late.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", { value: () => read.promise });
    fireEvent.change(
      document.querySelector<HTMLInputElement>('input[type="file"]')!,
      {
        target: { files: [file] },
      },
    );
    rendered.unmount();
    read.reject(new Error("late read"));
    await expect(read.promise).rejects.toThrow("late read");
    expect(rendered.router.state.location.pathname).toBe("/add/manual");
  });

  it("admits only one frozen Manual create while a delayed request is active", async () => {
    const request = deferred<MediaItem>();
    const user = userEvent.setup();
    const { importManual } = await renderManualAdd({
      importManual: () => request.promise,
    });
    const title = await screen.findByLabelText("Title (English)");
    await user.type(title, "First title");

    const save = screen.getByRole("button", { name: "Save Manual metadata" });
    fireEvent.click(save);
    await waitFor(() => expect(importManual).toHaveBeenCalledTimes(1));
    fireEvent.click(save);
    fireEvent.change(title, { target: { value: "Later title" } });

    expect(importManual).toHaveBeenCalledWith({
      collection_id: null,
      document: expect.objectContaining({ titles: { en: "First title" } }),
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saving Manual metadata…",
    );
    request.resolve(
      itemFromDocument(createManualDocumentFixture("First title")),
    );
    expect(
      await screen.findByRole("heading", { name: "First title" }),
    ).toBeVisible();
  });

  it("does not let a stale JSON file read overwrite directly edited source or submit while reading", async () => {
    const read = deferred<string>();
    const { importManual } = await renderManualAdd();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Complete JSON" }));
    const file = new File(["ignored"], "manual.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", { value: () => read.promise });
    const input =
      document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { files: [file] } });
    expect(screen.getByRole("status")).toHaveTextContent("Reading file…");
    fireEvent.click(screen.getByRole("button", { name: "Import Manual JSON" }));
    expect(importManual).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: JSON.stringify(createManualDocumentFixture("Typed")) },
    });
    read.resolve(JSON.stringify(createManualDocumentFixture("Stale")));
    await waitFor(() =>
      expect(screen.getByLabelText("Manual JSON")).toHaveValue(
        JSON.stringify(createManualDocumentFixture("Typed")),
      ),
    );
  });

  it("retains JSON source when the current local file read fails", async () => {
    const read = deferred<string>();
    await renderManualAdd();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Complete JSON" }));
    const source = screen.getByLabelText("Manual JSON");
    fireEvent.change(source, { target: { value: '{"previous":true}' } });
    const file = new File(["ignored"], "broken.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", { value: () => read.promise });
    fireEvent.change(
      document.querySelector<HTMLInputElement>('input[type="file"]')!,
      {
        target: { files: [file] },
      },
    );
    read.reject(new Error("unavailable"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not read the file. Previous text was kept.",
    );
    expect(source).toHaveValue('{"previous":true}');
  });

  it("keeps duplicate confirmation exclusive while confirmation is pending", async () => {
    const confirmation = deferred<MediaItem>();
    const importManual = vi.fn(async () => {
      throw new ControlFailure("confirmation_required", 409, null, "token");
    });
    const confirmManual = vi.fn(() => confirmation.promise);
    await renderManualAdd({ importManual, confirmManual });
    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Duplicate" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    const confirm = await screen.findByRole("button", {
      name: "Confirm revision",
    });
    fireEvent.click(confirm);
    await waitFor(() => expect(confirmManual).toHaveBeenCalledTimes(1));
    fireEvent.click(confirm);
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    confirmation.reject(new ControlFailure("selection_expired", 410));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The selection expired. Submit the Manual document again.",
    );
    expect(screen.getByLabelText("Title (English)")).toHaveValue("Duplicate");
  });

  it("supersedes JSON reads on replacement, clearing, and a mode switch", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    await renderManualAdd();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Complete JSON" }));
    const input =
      document.querySelector<HTMLInputElement>('input[type="file"]')!;
    const fileA = new File(["a"], "a.json", { type: "application/json" });
    const fileB = new File(["b"], "b.json", { type: "application/json" });
    Object.defineProperty(fileA, "text", { value: () => first.promise });
    Object.defineProperty(fileB, "text", { value: () => second.promise });
    fireEvent.change(input, { target: { files: [fileA] } });
    fireEvent.change(input, { target: { files: [fileB] } });
    second.resolve('{"second":true}');
    await waitFor(() =>
      expect(screen.getByLabelText("Manual JSON")).toHaveValue(
        '{"second":true}',
      ),
    );
    first.resolve('{"first":true}');
    fireEvent.change(input, { target: { files: [] } });
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Structured entry" }));
    expect(
      screen.getByRole("button", { name: "Structured entry" }),
    ).toBeEnabled();
  });

  it("preserves raw list text across mode return and normalizes it only in the structured request", async () => {
    const user = userEvent.setup();
    const { importManual } = await renderManualAdd();

    await user.type(
      await screen.findByLabelText("Title (English)"),
      "Raw lists",
    );
    await user.click(screen.getByRole("button", { name: "Additional fields" }));
    const rawLists = [
      ["Genres", "Drama, Comedy, "],
      ["Tags", "one, two, "],
      ["Countries", "US, CA, "],
      ["Studios", "North, South, "],
    ] as const;
    for (const [label, value] of rawLists) {
      await user.type(screen.getByLabelText(label), value);
      await user.tab();
    }
    await user.click(screen.getByRole("button", { name: "Complete JSON" }));
    await user.click(screen.getByRole("button", { name: "Structured entry" }));
    await user.click(screen.getByRole("button", { name: "Additional fields" }));

    for (const [label, value] of rawLists) {
      expect(screen.getByLabelText(label)).toHaveValue(value);
    }
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    expect(importManual).toHaveBeenCalledWith({
      collection_id: null,
      document: expect.objectContaining({
        countries: ["US", "CA"],
        genres: ["Drama", "Comedy"],
        studios: ["North", "South"],
        tags: ["one", "two"],
      }),
    });
  });

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

  it("rejects oversized JSON files before reading and bounds pasted text", async () => {
    const { importManual } = await renderManualAdd();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Complete JSON" }));
    const source = screen.getByLabelText("Manual JSON");
    fireEvent.change(source, { target: { value: "retained source" } });
    const file = new File(["x".repeat(1024 * 1024 + 1)], "large.json", {
      type: "application/json",
    });
    const read = vi.fn(async () => "unexpected read");
    Object.defineProperty(file, "text", { value: read });
    fireEvent.change(
      document.querySelector<HTMLInputElement>('input[type="file"]')!,
      { target: { files: [file] } },
    );
    expect(read).not.toHaveBeenCalled();
    expect(source).toHaveValue("retained source");
    expect(screen.getByRole("alert")).toHaveTextContent("one mebibyte");
    fireEvent.change(source, {
      target: { value: "x".repeat(1024 * 1024 + 1) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import Manual JSON" }));
    expect(screen.getByRole("alert")).toHaveTextContent("one mebibyte");
    expect(importManual).not.toHaveBeenCalled();
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
    const dialog = await screen.findByRole("dialog", {
      name: "Confirm Manual revision",
    });
    await waitFor(() => expect(dialog).toBeVisible());
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

  it("requires explicit consent before a structured create discards a JSON draft", async () => {
    const user = userEvent.setup();
    const { importManual, router } = await renderManualAdd();
    await user.type(
      await screen.findByLabelText("Title (English)"),
      "Structured",
    );
    await user.click(screen.getByRole("button", { name: "Complete JSON" }));
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: {
        value: JSON.stringify(createManualDocumentFixture("JSON draft")),
      },
    });
    await user.click(screen.getByRole("button", { name: "Structured entry" }));
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );

    const review = await screen.findByRole("dialog", {
      name: "Review unsaved draft",
    });
    await waitFor(() => expect(review).toBeVisible());
    const continueButton = within(review).getByRole("button", {
      name: "Continue saving",
    });
    expect(continueButton.style.height).toBe("auto");
    expect(
      getComputedStyle(within(continueButton).getByText("Continue saving"))
        .whiteSpace,
    ).toBe("normal");
    expect(screen.getByLabelText("Title (English)")).toBeDisabled();
    const mode = screen.getByRole("button", { name: "Complete JSON" });
    expect(mode).toBeDisabled();
    fireEvent.submit(
      screen
        .getByRole("button", { name: "Save Manual metadata" })
        .closest("form")!,
    );
    await act(async () => {
      await router.navigate("/");
    });
    expect(router.state.location.pathname).toBe("/add/manual");
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(importManual).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(review).not.toBeInTheDocument());
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Save Manual metadata" }),
      ).toHaveFocus(),
    );
    await user.click(screen.getByRole("button", { name: "Complete JSON" }));
    expect(screen.getByLabelText("Manual JSON")).toHaveValue(
      JSON.stringify(createManualDocumentFixture("JSON draft")),
    );
  });

  it("uses the shared collection for JSON without a structured-draft review", async () => {
    const user = userEvent.setup();
    const { importManual } = await renderManualAdd();
    await user.click(
      await screen.findByRole("button", { name: "Complete JSON" }),
    );
    const collection = screen.getByRole("combobox", { name: "Collection" });
    await user.click(collection);
    await user.keyboard("{ArrowDown}{Enter}");
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: {
        value: JSON.stringify(createManualDocumentFixture("JSON collection")),
      },
    });
    await user.click(
      screen.getByRole("button", { name: "Import Manual JSON" }),
    );
    await waitFor(() => expect(importManual).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByRole("dialog", { name: "Review unsaved draft" }),
    ).not.toBeInTheDocument();
    expect(importManual).toHaveBeenCalledWith(
      expect.objectContaining({ collection_id: "favorites" }),
    );
  });

  it("invalidates a pending JSON file read when switching modes", async () => {
    const read = deferred<string>();
    await renderManualAdd();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Complete JSON" }));
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: '{"kept":true}' },
    });
    const file = new File(["ignored"], "pending.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", { value: () => read.promise });
    fireEvent.change(
      document.querySelector<HTMLInputElement>('input[type="file"]')!,
      { target: { files: [file] } },
    );
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Structured entry" }));
    read.resolve('{"stale":true}');
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Complete JSON" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Manual JSON")).toHaveValue('{"kept":true}'),
    );
  });

  it("invalidates a pending JSON read when its file selection is cleared", async () => {
    const read = deferred<string>();
    await renderManualAdd();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Complete JSON" }));
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: '{"kept":true}' },
    });
    const file = new File(["ignored"], "pending.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", { value: () => read.promise });
    const input =
      document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.change(input, { target: { files: [] } });
    read.resolve('{"stale":true}');
    await waitFor(() =>
      expect(screen.getByLabelText("Manual JSON")).toHaveValue('{"kept":true}'),
    );
  });

  it("reviews forward history with Stay and explicit leave", async () => {
    const { router } = await renderManualAdd({
      initialEntries: ["/add/manual", "/"],
      initialIndex: 0,
    });
    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Forward draft" },
    });
    void router.navigate(1);
    const dialog = await screen.findByRole("dialog", {
      name: "Unsaved changes",
    });
    await waitFor(() => expect(dialog).toBeVisible());
    await userEvent.setup().click(screen.getByRole("button", { name: "Stay" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Unsaved changes" }),
      ).not.toBeInTheDocument(),
    );
    expect(router.state.location.pathname).toBe("/add/manual");
    void router.navigate(1);
    const leaveDialog = await screen.findByRole("dialog", {
      name: "Unsaved changes",
    });
    await waitFor(() => expect(leaveDialog).toBeVisible());
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Discard and leave" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });

  it("re-prompts alternate-draft consent after duplicate cancellation", async () => {
    const user = userEvent.setup();
    const importManual = vi.fn(async () => {
      throw new ControlFailure("confirmation_required", 409, null, "token");
    });
    await renderManualAdd({ importManual });
    await user.type(
      await screen.findByLabelText("Title (English)"),
      "Structured",
    );
    await user.click(screen.getByRole("button", { name: "Complete JSON" }));
    fireEvent.change(screen.getByLabelText("Manual JSON"), {
      target: { value: JSON.stringify(createManualDocumentFixture("JSON")) },
    });
    await user.click(screen.getByRole("button", { name: "Structured entry" }));
    const save = screen.getByRole("button", { name: "Save Manual metadata" });
    await user.click(save);
    const alternate = await screen.findByRole("dialog", {
      name: "Review unsaved draft",
    });
    await user.click(
      within(alternate).getByRole("button", { name: "Continue saving" }),
    );
    const duplicate = await screen.findByRole("dialog", {
      name: "Confirm Manual revision",
    });
    await user.click(within(duplicate).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("dialog", { name: "Confirm Manual revision" }),
      ).not.toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "Complete JSON" }));
    expect(screen.getByLabelText("Manual JSON")).toHaveValue(
      JSON.stringify(createManualDocumentFixture("JSON")),
    );
    await user.click(screen.getByRole("button", { name: "Structured entry" }));
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    expect(
      await screen.findByRole("dialog", { name: "Review unsaved draft" }),
    ).toBeInTheDocument();
    expect(importManual).toHaveBeenCalledTimes(1);
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
