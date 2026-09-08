import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
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
import {
  manualMovieDetail,
  manualSeriesDetail,
  mediaDetail,
} from "../mocks/fixtures";

type MediaItem = components["schemas"]["MediaItemDetail"];
type ManualDocument = components["schemas"]["ManualDocumentV1"];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

async function renderEdit(
  item: MediaItem,
  options?: {
    confirmManual?: (token: string) => Promise<MediaItem>;
    editManual?: (id: string, document: ManualDocument) => Promise<MediaItem>;
    getMediaItem?: (id: string) => Promise<MediaItem>;
    importEpisodes?: (id: string, csv: string) => Promise<MediaItem>;
    initialEntries?: string[];
    initialIndex?: number;
  },
) {
  const editManual = vi.fn(
    options?.editManual ??
      (async (_id: string, document: ManualDocument) => ({
        ...item,
        metadata: document,
      })),
  );
  const client = {
    bootstrapSession: vi.fn().mockResolvedValue({
      csrf_token: "csrf",
      metadata_locale: "en",
      supported_locales: ["en", "ru"],
      ui_locale: "en",
    }),
    confirmManual: vi.fn(options?.confirmManual),
    editManual,
    getMediaItem: vi.fn(options?.getMediaItem ?? (async () => item)),
    importEpisodes: vi.fn(options?.importEpisodes ?? (async () => item)),
    listCollections: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  } as unknown as ControlClient;
  const router = createMemoryRouter(appRoutes, {
    initialEntries: options?.initialEntries ?? [`/items/${item.id}/edit`],
    initialIndex: options?.initialIndex,
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
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
  return { client, editManual, queryClient, router, unmount: view.unmount };
}

describe("ManualEditPage", () => {
  it("reinitializes an edit draft for a different item identity", async () => {
    const replacement = {
      ...manualSeriesDetail,
      collection_id: "replacement-collection",
      id: "manual-series-replacement",
      metadata: {
        ...manualSeriesDetail.metadata,
        genres: ["Replacement genre"],
        tags: ["replacement-tag"],
        titles: {
          ...manualSeriesDetail.metadata.titles,
          en: "Replacement series",
        },
      },
    } satisfies MediaItem;
    const { router } = await renderEdit(manualSeriesDetail, {
      getMediaItem: async (id) =>
        id === replacement.id ? replacement : manualSeriesDetail,
    });
    await screen.findByLabelText("Episode CSV");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Additional fields" }));
    await user.type(screen.getByLabelText("Tags"), " draft");
    fireEvent.change(screen.getByLabelText("Episode CSV"), {
      target: { value: "season_number,episode_number,title\n1,1,Draft\n" },
    });
    void router.navigate(`/items/${replacement.id}/edit`);
    const leaveDialog = await screen.findByRole("dialog", {
      name: "Unsaved changes",
    });
    await waitFor(() => expect(leaveDialog).toBeVisible());
    await user.click(screen.getByRole("button", { name: "Discard and leave" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Title (English)")).toHaveValue(
        "Replacement series",
      ),
    );
    await user.click(screen.getByRole("button", { name: "Additional fields" }));
    expect(screen.getByLabelText("Countries")).toHaveValue("DE");
    expect(screen.getByLabelText("Genres")).toHaveValue("Replacement genre");
    expect(screen.getByLabelText("Studios")).toHaveValue("Fixture Television");
    expect(screen.getByLabelText("Tags")).toHaveValue("replacement-tag");
    expect(screen.getByLabelText("Episode CSV")).toHaveValue("");

    void router.navigate("/");
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
    expect(
      screen.queryByRole("dialog", { name: "Unsaved changes" }),
    ).not.toBeInTheDocument();
  });

  it("retains an existing edit draft through a background refetch failure", async () => {
    let calls = 0;
    const getMediaItem = vi.fn(async () => {
      calls += 1;
      if (calls === 1) return manualSeriesDetail;
      throw new Error("background refetch failed");
    });
    const { queryClient } = await renderEdit(manualSeriesDetail, {
      getMediaItem,
    });
    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Preserved draft" },
    });
    await queryClient.invalidateQueries({
      queryKey: ["control", "media-item", manualSeriesDetail.id, "en"],
    });
    await waitFor(() => expect(getMediaItem).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText("Title (English)")).toHaveValue(
      "Preserved draft",
    );
    expect(
      screen.queryByRole("alert", { name: "Unexpected response" }),
    ).not.toBeInTheDocument();
  });

  it("treats CSV as a dirty edit draft and permits clean navigation without a review", async () => {
    const { router } = await renderEdit(manualSeriesDetail);
    await screen.findByLabelText("Episode CSV");
    void router.navigate("/");
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));

    const dirty = await renderEdit(manualSeriesDetail);
    fireEvent.change(await screen.findByLabelText("Episode CSV"), {
      target: { value: "season_number,episode_number,title\n1,1,Draft\n" },
    });
    void dirty.router.navigate("/");
    expect(
      await screen.findByRole("dialog", { name: "Unsaved changes" }),
    ).toBeVisible();
  });

  it("admits one frozen structured save and excludes a competing CSV import", async () => {
    const request = deferred<MediaItem>();
    const { client, editManual } = await renderEdit(manualSeriesDetail, {
      editManual: () => request.promise,
    });
    const title = await screen.findByLabelText("Title (English)");
    fireEvent.change(title, { target: { value: "First edit" } });
    const save = screen.getByRole("button", { name: "Save Manual metadata" });
    fireEvent.click(save);
    await waitFor(() => expect(editManual).toHaveBeenCalledTimes(1));
    fireEvent.click(save);
    fireEvent.change(screen.getByLabelText("Episode CSV"), {
      target: { value: "season_number,episode_number,title\n1,1,Later\n" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Import episode CSV" }));

    expect(editManual).toHaveBeenCalledWith(
      manualSeriesDetail.id,
      expect.objectContaining({
        titles: { en: "First edit", ru: manualSeriesDetail.metadata.titles.ru },
      }),
    );
    expect(client.importEpisodes).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saving Manual metadata…",
    );
    request.resolve({
      ...manualSeriesDetail,
      metadata: {
        ...manualSeriesDetail.metadata,
        titles: { en: "First edit", ru: manualSeriesDetail.metadata.titles.ru },
      },
    });
  });

  it("keeps CSV text when a stale local file read resolves after direct editing", async () => {
    const read = deferred<string>();
    await renderEdit(manualSeriesDetail);
    await screen.findByLabelText("Episode CSV");
    const file = new File(["ignored"], "episodes.csv", { type: "text/csv" });
    Object.defineProperty(file, "text", { value: () => read.promise });
    const input =
      document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, { target: { files: [file] } });
    expect(screen.getByRole("status")).toHaveTextContent("Reading file…");
    fireEvent.change(screen.getByLabelText("Episode CSV"), {
      target: { value: "season_number,episode_number,title\n1,1,Typed\n" },
    });
    read.resolve("season_number,episode_number,title\n1,1,Stale\n");
    await waitFor(() =>
      expect(screen.getByLabelText("Episode CSV")).toHaveValue(
        "season_number,episode_number,title\n1,1,Typed\n",
      ),
    );
  });

  it("retains CSV source when the current local file read fails", async () => {
    const read = deferred<string>();
    const user = userEvent.setup();
    await renderEdit(manualSeriesDetail);
    const source = await screen.findByLabelText("Episode CSV");
    await user.type(
      source,
      "season_number,episode_number,title\\n1,1,Previous\\n",
    );
    const file = new File(["ignored"], "broken.csv", { type: "text/csv" });
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
    expect(source).toHaveValue(
      "season_number,episode_number,title\\n1,1,Previous\\n",
    );
  });

  it("supersedes CSV replacement, clear, and oversized-file reads", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const third = deferred<string>();
    await renderEdit(manualSeriesDetail);
    await screen.findByLabelText("Episode CSV");
    const input =
      document.querySelector<HTMLInputElement>('input[type="file"]')!;
    const a = new File(["a"], "a.csv", { type: "text/csv" });
    const b = new File(["b"], "b.csv", { type: "text/csv" });
    const c = new File(["c"], "c.csv", { type: "text/csv" });
    Object.defineProperty(a, "text", { value: () => first.promise });
    Object.defineProperty(b, "text", { value: () => second.promise });
    Object.defineProperty(c, "text", { value: () => third.promise });
    fireEvent.change(input, { target: { files: [a] } });
    fireEvent.change(input, { target: { files: [b] } });
    second.resolve("second");
    await waitFor(() =>
      expect(screen.getByLabelText("Episode CSV")).toHaveValue("second"),
    );
    first.resolve("first");
    fireEvent.change(input, { target: { files: [c] } });
    fireEvent.change(input, { target: { files: [] } });
    third.resolve("third");
    const oversized = new File(["x".repeat(1024 * 1024 + 1)], "large.csv", {
      type: "text/csv",
    });
    fireEvent.change(input, { target: { files: [oversized] } });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Episode CSV must not exceed one mebibyte.",
    );
    expect(screen.getByLabelText("Episode CSV")).toHaveValue("second");
  });

  it("ignores edit and CSV-read completion after the edit page unmounts", async () => {
    const save = deferred<MediaItem>();
    const rendered = await renderEdit(manualSeriesDetail, {
      editManual: () => save.promise,
    });
    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Abandoned" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    await waitFor(() => expect(rendered.editManual).toHaveBeenCalledTimes(1));
    rendered.unmount();
    save.resolve({
      ...manualSeriesDetail,
      metadata: {
        ...manualSeriesDetail.metadata,
        titles: { en: "Abandoned", ru: manualSeriesDetail.metadata.titles.ru },
      },
    });
    await save.promise;
    expect(rendered.router.state.location.pathname).toBe(
      `/items/${manualSeriesDetail.id}/edit`,
    );

    const read = deferred<string>();
    const csv = await renderEdit(manualSeriesDetail);
    await screen.findByLabelText("Episode CSV");
    const file = new File(["ignored"], "late.csv", { type: "text/csv" });
    Object.defineProperty(file, "text", { value: () => read.promise });
    fireEvent.change(
      document.querySelector<HTMLInputElement>('input[type="file"]')!,
      {
        target: { files: [file] },
      },
    );
    csv.unmount();
    read.reject(new Error("late read"));
    await expect(read.promise).rejects.toThrow("late read");
    expect(csv.router.state.location.pathname).toBe(
      `/items/${manualSeriesDetail.id}/edit`,
    );
  });

  it("rejects a direct non-Manual bookmark without a mutation", async () => {
    const { editManual } = await renderEdit(mediaDetail);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This item is not editable as Manual metadata.",
    );
    expect(
      screen.queryByRole("button", { name: "Save Manual metadata" }),
    ).not.toBeInTheDocument();
    expect(editManual).not.toHaveBeenCalled();
  });

  it("preserves rich fields and other locale titles while deliberately removing a season", async () => {
    const user = userEvent.setup();
    const { editManual, router } = await renderEdit(manualSeriesDetail);

    expect(await screen.findByLabelText("External ID")).toHaveValue(
      manualSeriesDetail.external_id,
    );
    expect(screen.getByLabelText("Media kind")).toHaveValue("Series");
    expect(
      screen.queryByRole("combobox", { name: "Collection" }),
    ).not.toBeInTheDocument();
    const title = screen.getByLabelText("Title (English)");
    await user.clear(title);
    await user.type(title, "Edited rich series");
    const specials = screen.getByRole("group", { name: "Season 0" });
    await user.click(
      within(specials).getByRole("button", { name: "Remove season 0" }),
    );
    await user.click(await screen.findByRole("button", { name: "Continue" }));
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Edited rich series" }),
    ).toBeVisible();
    expect(router.state.location.pathname).toBe(
      `/items/${manualSeriesDetail.id}`,
    );
    expect(editManual).toHaveBeenCalledWith(
      manualSeriesDetail.id,
      expect.objectContaining({
        artwork: manualSeriesDetail.metadata.artwork,
        external_id: manualSeriesDetail.external_id,
        kind: "series",
        people: manualSeriesDetail.metadata.people,
        provider_ids: manualSeriesDetail.metadata.provider_ids,
        ratings: manualSeriesDetail.metadata.ratings,
        seasons: [manualSeriesDetail.metadata.seasons[1]],
        titles: {
          en: "Edited rich series",
          ru: "\u0420\u0443\u0447\u043d\u043e\u0439 \u0441\u0435\u0440\u0438\u0430\u043b",
        },
      }),
    );
  }, 10_000);

  it("changes one rich movie field without dropping unexposed metadata", async () => {
    const user = userEvent.setup();
    const { editManual } = await renderEdit(manualMovieDetail);
    const title = await screen.findByLabelText("Title (English)");
    await user.clear(title);
    await user.type(title, "Edited rich movie");
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Edited rich movie" }),
    ).toBeVisible();
    expect(editManual).toHaveBeenCalledWith(
      manualMovieDetail.id,
      expect.objectContaining({
        artwork: manualMovieDetail.metadata.artwork,
        external_id: manualMovieDetail.external_id,
        people: manualMovieDetail.metadata.people,
        provider_ids: manualMovieDetail.metadata.provider_ids,
        ratings: manualMovieDetail.metadata.ratings,
        titles: {
          en: "Edited rich movie",
          ru: "\u0420\u0443\u0447\u043d\u043e\u0439 \u0444\u0438\u043b\u044c\u043c",
        },
      }),
    );
  });

  it("requires explicit confirmation before replacing an existing Manual identity", async () => {
    const user = userEvent.setup();
    const token = "edit-confirmation-token";
    const updated = {
      ...manualSeriesDetail,
      metadata: {
        ...manualSeriesDetail.metadata,
        titles: { ...manualSeriesDetail.metadata.titles, en: "Confirmed edit" },
      },
    };
    const editManual = vi.fn(async () => {
      throw new ControlFailure("confirmation_required", 409, null, token);
    });
    const confirmManual = vi.fn(async () => updated);
    const { client, router } = await renderEdit(manualSeriesDetail, {
      confirmManual,
      editManual,
    });

    const title = await screen.findByLabelText("Title (English)");
    await user.clear(title);
    await user.type(title, "Confirmed edit");
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Confirm revision" }),
    );

    expect(
      await screen.findByRole("heading", { name: "Confirmed edit" }),
    ).toBeVisible();
    expect(client.confirmManual).toHaveBeenCalledWith(token);
    expect(client.confirmManual).toHaveBeenCalledTimes(1);
    expect(router.state.location.pathname).toBe(
      `/items/${manualSeriesDetail.id}`,
    );
  }, 10_000);

  it("submits one raw episode CSV request and opens the resulting revision", async () => {
    const user = userEvent.setup();
    const csv = "season_number,episode_number,title\n0,2,Second special\n";
    const updated = {
      ...manualSeriesDetail,
      metadata: {
        ...manualSeriesDetail.metadata,
        titles: { ...manualSeriesDetail.metadata.titles, en: "CSV revision" },
      },
    };
    const importEpisodes = vi.fn(async () => updated);
    const { client, router } = await renderEdit(manualSeriesDetail, {
      importEpisodes,
    });

    await screen.findByLabelText("Episode CSV");
    await user.type(screen.getByLabelText("Episode CSV"), csv);
    await user.click(
      screen.getByRole("button", { name: "Import episode CSV" }),
    );

    expect(
      await screen.findByRole("heading", { name: "CSV revision" }),
    ).toBeVisible();
    expect(client.importEpisodes).toHaveBeenCalledWith(
      manualSeriesDetail.id,
      csv,
    );
    expect(client.importEpisodes).toHaveBeenCalledTimes(1);
    expect(router.state.location.pathname).toBe(
      `/items/${manualSeriesDetail.id}`,
    );
  }, 10_000);

  it("rejects empty and over-one-mebibyte CSV before any request", async () => {
    const user = userEvent.setup();
    const { client } = await renderEdit(manualSeriesDetail);
    await screen.findByLabelText("Episode CSV");

    await user.click(
      screen.getByRole("button", { name: "Import episode CSV" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Enter episode CSV data.",
    );
    const fileInput =
      document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(fileInput).not.toBeNull();
    await user.upload(
      fileInput!,
      new File(
        ["season_number,episode_number,title\n1,1,Pilot\n"],
        "episodes.csv",
        {
          type: "text/csv",
        },
      ),
    );
    expect(screen.getByLabelText("Episode CSV")).toHaveValue(
      "season_number,episode_number,title\n1,1,Pilot\n",
    );
    fireEvent.change(screen.getByLabelText("Episode CSV"), {
      target: { value: "x".repeat(1024 * 1024 + 1) },
    });
    await user.click(
      screen.getByRole("button", { name: "Import episode CSV" }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Episode CSV must not exceed one mebibyte.",
    );
    expect(client.importEpisodes).not.toHaveBeenCalled();
  }, 10_000);

  it("shows a safe atomic CSV error without changing the visible revision", async () => {
    const user = userEvent.setup();
    const importEpisodes = vi.fn(async () => {
      throw new ControlFailure("episode_csv_invalid", 422, "safe-request");
    });
    const { client, router } = await renderEdit(manualSeriesDetail, {
      importEpisodes,
    });
    await user.type(
      await screen.findByLabelText("Episode CSV"),
      "season_number,episode_number,title\n1,bad,Pilot\n",
    );
    await user.click(
      screen.getByRole("button", { name: "Import episode CSV" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The episode CSV is invalid; no episodes were changed.",
    );
    expect(screen.queryByText("safe-request")).not.toBeInTheDocument();
    expect(client.importEpisodes).toHaveBeenCalledTimes(1);
    expect(router.state.location.pathname).toBe(
      `/items/${manualSeriesDetail.id}/edit`,
    );
    expect(screen.getByLabelText("Title (English)")).toHaveValue(
      "Manual Series",
    );
  });

  it("blocks CSV while structured fields are dirty and resets only the structured draft after confirmation", async () => {
    const user = userEvent.setup();
    const { client } = await renderEdit(manualSeriesDetail);
    await screen.findByLabelText("Title (English)");
    await user.click(screen.getByRole("button", { name: "Additional fields" }));
    await user.type(screen.getByLabelText("Tags"), "draft");
    fireEvent.change(screen.getByLabelText("Episode CSV"), {
      target: { value: "season_number,episode_number,title\n1,1,Pilot\n" },
    });
    await user.click(
      screen.getByRole("button", { name: "Import episode CSV" }),
    );

    expect(
      await screen.findByText(
        "Save the form first or discard its changes before importing CSV.",
      ),
    ).toBeVisible();
    expect(client.importEpisodes).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Discard form changes" }),
    );
    const resetDialog = await screen.findByRole("dialog", {
      name: "Discard form changes?",
    });
    await waitFor(() => expect(resetDialog).toBeVisible());
    expect(
      within(resetDialog).getByRole("button", { name: "Cancel" }),
    ).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(resetDialog).not.toBeInTheDocument());
    const resetTrigger = screen.getByRole("button", {
      name: "Discard form changes",
    });
    await waitFor(() => expect(resetTrigger).toHaveFocus());
    expect(screen.getByLabelText("Tags")).toHaveValue(
      `${manualSeriesDetail.metadata.tags.join(", ")}draft`,
    );
    await user.click(resetTrigger);
    const reopened = await screen.findByRole("dialog", {
      name: "Discard form changes?",
    });
    await waitFor(() => expect(reopened).toBeVisible());
    await user.click(
      within(reopened).getByRole("button", { name: "Discard form changes" }),
    );
    expect(screen.getByLabelText("Title (English)")).toHaveValue(
      "Manual Series",
    );
    expect(screen.getByLabelText("Episode CSV")).toHaveValue(
      "season_number,episode_number,title\n1,1,Pilot\n",
    );
  });

  it("requires fresh CSV-draft consent for structured retry after an error", async () => {
    const user = userEvent.setup();
    const editManual = vi.fn(async () => {
      throw new ControlFailure("request_body_invalid", 422);
    });
    await renderEdit(manualSeriesDetail, { editManual });
    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Retry title" },
    });
    fireEvent.change(screen.getByLabelText("Episode CSV"), {
      target: { value: "season_number,episode_number,title\n1,1,CSV\n" },
    });
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    let review = await screen.findByRole("dialog", {
      name: "Review unsaved draft",
    });
    await waitFor(() => expect(review).toBeVisible());
    expect(
      within(review).getByRole("button", { name: "Cancel" }),
    ).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(review).not.toBeInTheDocument());
    const save = screen.getByRole("button", { name: "Save Manual metadata" });
    await waitFor(() => expect(save).toHaveFocus());
    await user.click(save);
    review = await screen.findByRole("dialog", {
      name: "Review unsaved draft",
    });
    await waitFor(() => expect(review).toBeVisible());
    expect(screen.getByLabelText("Title (English)")).toBeDisabled();
    expect(screen.getByLabelText("Episode CSV")).toBeDisabled();
    await user.click(
      within(review).getByRole("button", { name: "Continue saving" }),
    );
    await waitFor(() => expect(editManual).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Episode CSV")).toHaveValue(
      "season_number,episode_number,title\n1,1,CSV\n",
    );
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );
    expect(
      await screen.findByRole("dialog", { name: "Review unsaved draft" }),
    ).toBeInTheDocument();
    expect(editManual).toHaveBeenCalledTimes(1);
  });

  it("invalidates a pending CSV read when its file selection is cleared", async () => {
    const read = deferred<string>();
    await renderEdit(manualSeriesDetail);
    const csv = await screen.findByLabelText("Episode CSV");
    fireEvent.change(csv, { target: { value: "kept" } });
    const file = new File(["ignored"], "pending.csv", { type: "text/csv" });
    Object.defineProperty(file, "text", { value: () => read.promise });
    const input =
      document.querySelector<HTMLInputElement>('input[type="file"]')!;
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.change(input, { target: { files: [] } });
    read.resolve("stale");
    await waitFor(() => expect(csv).toHaveValue("kept"));
  });

  it("reviews forward history with Stay and explicit leave", async () => {
    const { router } = await renderEdit(manualSeriesDetail, {
      initialEntries: [`/items/${manualSeriesDetail.id}/edit`, "/"],
      initialIndex: 0,
    });
    fireEvent.change(await screen.findByLabelText("Title (English)"), {
      target: { value: "Forward draft" },
    });
    const title = screen.getByLabelText("Title (English)");
    title.focus();
    void router.navigate(1);
    await screen.findByRole("dialog", { name: "Unsaved changes" });
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
    expect(router.state.location.pathname).toBe(
      `/items/${manualSeriesDetail.id}/edit`,
    );
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
});
