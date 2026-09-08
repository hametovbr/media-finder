import { MantineProvider } from "@mantine/core";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";

import type { components } from "../api/control.generated";
import { createUiI18n } from "../i18n";
import ru from "../locales/ru.json";
import { manualSeriesDetail } from "../mocks/fixtures";
import {
  createManualDocument,
  type ManualEditorEpisode,
  type ManualEditorDocument,
  type ManualEditorSeason,
  manualDocumentFromItem,
  withManualRowKeys,
} from "./manual-document";
import { ManualEditor } from "./manual-editor";

type Collection = components["schemas"]["CollectionView"];

const collections = [
  { archived: false, id: "favorites", name: "Favorites" },
] satisfies Collection[];

function keyed(document: ReturnType<typeof createManualDocument>) {
  let key = 0;
  return withManualRowKeys(document, () => `row-${++key}`);
}

function episode(rowKey: string, number: number): ManualEditorEpisode {
  return {
    air_date: null,
    number,
    ordering: null,
    plot: null,
    provider_ids: {},
    rowKey,
    runtime_minutes: null,
    title: `Episode ${number}`,
  };
}

function season(
  rowKey: string,
  number: number,
  episodes: ManualEditorEpisode[],
): ManualEditorSeason {
  return {
    episodes,
    number,
    plot: null,
    provider_ids: {},
    rowKey,
    title: `Season ${number}`,
  };
}

function newSeriesDocument(): ManualEditorDocument {
  const document = keyed(createManualDocument("series", "en"));
  document.seasons = [
    season("season-1", 1, [episode("episode-1", 1), episode("episode-2", 2)]),
    season("season-2", 2, [episode("episode-3", 1)]),
  ];
  return document;
}

function EditorHarness({
  disabled = false,
  initialCollectionId = null,
  initialDocument,
  onSubmit = () => undefined,
}: {
  disabled?: boolean;
  initialCollectionId?: string | null;
  initialDocument: ManualEditorDocument;
  onSubmit?: (
    document: ManualEditorDocument,
    collectionId: string | null,
  ) => void;
}) {
  const [document, setDocument] = useState(initialDocument);
  const [collectionId, setCollectionId] = useState(initialCollectionId);
  const [reviewing, setReviewing] = useState(false);
  const [rawLists, setRawLists] = useState({
    countries: initialDocument.countries.join(", "),
    genres: initialDocument.genres.join(", "),
    studios: initialDocument.studios.join(", "),
    tags: initialDocument.tags.join(", "),
  });

  return (
    <ManualEditor
      collectionId={collectionId}
      collections={collections}
      document={document}
      disabled={disabled || reviewing}
      onCollectionIdChange={setCollectionId}
      onDocumentChange={setDocument}
      onReviewChange={(nextReviewing) => setReviewing(nextReviewing)}
      onRawListsChange={setRawLists}
      onSubmit={onSubmit}
      rawLists={rawLists}
    />
  );
}

function renderEditor(props: Parameters<typeof EditorHarness>[0]) {
  const i18n = createUiI18n("en");
  return {
    ...render(
      <I18nextProvider i18n={i18n}>
        <MantineProvider>
          <EditorHarness {...props} />
        </MantineProvider>
      </I18nextProvider>,
    ),
    i18n,
  };
}

describe("ManualEditor", () => {
  it("renders common fields, locked edit identity, collection context, and Season 00", () => {
    let key = 0;
    const document = withManualRowKeys(
      manualDocumentFromItem(manualSeriesDetail, "en"),
      () => `rich-row-${++key}`,
    );

    renderEditor({
      initialCollectionId: "favorites",
      initialDocument: document,
    });

    expect(screen.getByLabelText("External ID")).toHaveValue(
      manualSeriesDetail.external_id,
    );
    expect(screen.getByLabelText("External ID")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Media kind")).toHaveValue("Series");
    expect(screen.getByLabelText("Media kind")).toHaveAttribute("readonly");
    expect(screen.getByLabelText("Title (English)")).toHaveValue(
      "Manual Series",
    );
    expect(screen.getByLabelText("Original title")).toHaveValue(
      "A Manual Series",
    );
    expect(screen.getByLabelText("Year")).toHaveValue("2025");
    expect(screen.getByLabelText("Plot")).toHaveValue(
      "A rich deterministic Manual series fixture.",
    );
    expect(screen.getByLabelText("Release date")).toHaveValue("2025-01-02");
    expect(screen.getByLabelText("Runtime (minutes)")).toHaveValue("48");
    expect(screen.getByLabelText("Genres")).toHaveValue("Mystery");
    expect(screen.getByLabelText("Tags")).toHaveValue("manual, rich");
    expect(screen.getByLabelText("Countries")).toHaveValue("DE");
    expect(screen.getByLabelText("Studios")).toHaveValue("Fixture Television");
    expect(screen.getByRole("combobox", { name: "Collection" })).toHaveValue(
      "Favorites",
    );

    const specials = screen.getByRole("group", { name: "Season 0" });
    expect(
      within(specials).getByRole("group", { name: "Episode 1" }),
    ).toBeVisible();
    expect(screen.getByTestId("manual-editor-layout")).toHaveStyle({
      minWidth: "0",
      width: "100%",
    });
  });

  it("toggles additional fields by keyboard and reports editable hierarchy counts", async () => {
    const user = userEvent.setup();
    renderEditor({
      initialDocument: newSeriesDocument(),
    });

    const disclosure = screen.getByRole("button", {
      name: "Additional fields",
    });
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByLabelText("Title (English)")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Media kind" })).toBeVisible();
    expect(screen.getByLabelText("Year")).toBeVisible();
    expect(screen.getByLabelText("Plot")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Collection" })).toBeVisible();
    expect(screen.getByText("Seasons: 2 · Episodes: 3")).toBeVisible();
    expect(screen.getByRole("group", { name: "Season 1" })).toBeVisible();

    const originalTitle = screen.getByLabelText("Original title");
    expect(originalTitle).toBeInTheDocument();
    expect(screen.getByLabelText("Release date")).toBeInTheDocument();
    expect(screen.getByLabelText("Runtime (minutes)")).toBeInTheDocument();
    expect(screen.getByLabelText("Genres")).toBeInTheDocument();
    expect(screen.getByLabelText("Tags")).toBeInTheDocument();
    expect(screen.getByLabelText("Countries")).toBeInTheDocument();
    expect(screen.getByLabelText("Studios")).toBeInTheDocument();

    disclosure.focus();
    await user.keyboard("{Enter}");
    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    await waitFor(() => expect(originalTitle).toBeVisible());
    await user.clear(originalTitle);
    await user.type(originalTitle, "Retained original title");

    disclosure.focus();
    await user.keyboard("{Enter}");
    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(originalTitle).toHaveValue("Retained original title");

    disclosure.focus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(originalTitle).toBeVisible());
    expect(originalTitle).toHaveValue("Retained original title");
  });

  it("keeps localized disclosure and destructive actions wrapping-friendly", async () => {
    const user = userEvent.setup();
    const view = renderEditor({
      initialDocument: newSeriesDocument(),
    });
    await view.i18n.changeLanguage("ru");

    const disclosure = screen.getByRole("button", {
      name: ru.manual.secondaryFields,
    });
    expect(disclosure.style.height).toBe("auto");
    expect(disclosure.style.minHeight).toBe("2.25rem");
    expect(disclosure.style.whiteSpace).toBe("normal");
    const removeSeason = within(
      screen.getByRole("group", {
        name: ru.manual.season.legend.replace("{{number}}", "1"),
      }),
    ).getByRole("button", {
      name: ru.manual.season.remove.replace("{{number}}", "1"),
    });
    expect(removeSeason.style.height).toBe("auto");
    expect(removeSeason.style.minHeight).toBe("2.25rem");
    expect(
      getComputedStyle(
        within(removeSeason).getByText(
          ru.manual.season.remove.replace("{{number}}", "1"),
        ),
      ).whiteSpace,
    ).toBe("normal");

    await user.click(removeSeason);
    const dialog = await screen.findByRole("dialog");
    const cancel = within(dialog).getByRole("button", {
      name: ru.manual.destructive.cancel,
    });
    expect(cancel.style.height).toBe("auto");
    expect(cancel.style.minHeight).toBe("2.25rem");
    const confirm = within(dialog).getByRole("button", {
      name: ru.manual.destructive.confirm,
    });
    expect(confirm.style.height).toBe("auto");
    expect(confirm.style.minHeight).toBe("2.25rem");
  });

  it("requires review before removing a season and focuses add season after confirmation", async () => {
    const user = userEvent.setup();
    renderEditor({
      initialDocument: newSeriesDocument(),
    });

    const firstSeason = screen.getByRole("group", { name: "Season 1" });
    const removeSeason = within(firstSeason).getByRole("button", {
      name: "Remove season 1",
    });
    removeSeason.focus();
    await user.keyboard("{Enter}");

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toBeVisible());
    expect(dialog).toHaveTextContent("Remove season 1 and its 2 episodes?");
    expect(screen.getByRole("button", { name: "Add season" })).toBeDisabled();
    expect(screen.getByLabelText("Title (English)")).toBeDisabled();

    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    expect(cancel).toHaveFocus();
    await user.click(cancel);
    await waitFor(() => expect(removeSeason).toHaveFocus());
    expect(screen.getByRole("group", { name: "Season 1" })).toBeInTheDocument();

    removeSeason.focus();
    await user.keyboard("{Enter}");
    const confirmation = await screen.findByRole("dialog");
    await waitFor(() => expect(confirmation).toBeVisible());
    await user.click(
      within(confirmation).getByRole("button", { name: "Continue" }),
    );

    expect(
      screen.queryByRole("group", { name: "Season 1" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Season 2" })).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Add season" })).toHaveFocus(),
    );
  });

  it("captures an episode target, restores focus on cancel, and focuses add episode after confirmation", async () => {
    const user = userEvent.setup();
    renderEditor({
      initialDocument: newSeriesDocument(),
    });

    const firstSeason = screen.getByRole("group", { name: "Season 1" });
    const removeEpisode = within(firstSeason).getByRole("button", {
      name: "Remove episode 1",
    });
    removeEpisode.focus();
    await user.keyboard("{Enter}");

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toBeVisible());
    expect(dialog).toHaveTextContent("Remove episode 1?");
    expect(dialog).toHaveTextContent("This removes 1 episode.");
    expect(
      within(dialog).getByRole("button", { name: "Cancel" }),
    ).toHaveFocus();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(removeEpisode).toHaveFocus());
    expect(
      within(screen.getByRole("group", { name: "Season 1" })).getByRole(
        "group",
        { name: "Episode 1" },
      ),
    ).toBeInTheDocument();

    removeEpisode.focus();
    await user.keyboard("{Enter}");
    const confirmation = await screen.findByRole("dialog");
    await waitFor(() => expect(confirmation).toBeVisible());
    await user.click(
      within(confirmation).getByRole("button", { name: "Continue" }),
    );
    await waitFor(() =>
      expect(
        within(screen.getByRole("group", { name: "Season 1" })).queryByRole(
          "group",
          { name: "Episode 1" },
        ),
      ).not.toBeInTheDocument(),
    );
    await waitFor(() =>
      expect(
        within(screen.getByRole("group", { name: "Season 1" })).getByRole(
          "button",
          { name: "Add episode" },
        ),
      ).toHaveFocus(),
    );
  });

  it("adds season and episode rows from the keyboard", async () => {
    const user = userEvent.setup();
    renderEditor({
      initialDocument: keyed(createManualDocument("series", "en")),
    });

    const addSeason = screen.getByRole("button", { name: "Add season" });
    addSeason.focus();
    await user.keyboard("{Enter}");

    const createdSeason = screen.getByRole("group", { name: "Season 1" });
    const addEpisode = within(createdSeason).getByRole("button", {
      name: "Add episode",
    });
    addEpisode.focus();
    await user.keyboard("{Enter}");
    expect(
      within(createdSeason).getByRole("group", { name: "Episode 1" }),
    ).toBeVisible();
  });

  it("defers a populated new series-to-movie change and focuses the kind selector", async () => {
    const user = userEvent.setup();
    renderEditor({
      initialDocument: newSeriesDocument(),
    });

    const kind = screen.getByRole("combobox", { name: "Media kind" });
    kind.focus();
    await user.click(kind);
    await user.keyboard("{ArrowUp}{Enter}");

    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toBeVisible());
    expect(dialog).toHaveTextContent(
      "Changing this new series to a movie removes 2 seasons and 3 episodes.",
    );
    expect(
      within(dialog).getByRole("button", { name: "Cancel" }),
    ).toHaveFocus();
    expect(screen.getByRole("group", { name: "Season 1" })).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(kind).toHaveFocus());
    expect(kind).toHaveValue("Series");
    expect(screen.getByRole("group", { name: "Season 1" })).toBeInTheDocument();

    await user.click(kind);
    await user.keyboard("{ArrowUp}{Enter}");
    const confirmed = await screen.findByRole("dialog");
    await waitFor(() => expect(confirmed).toBeVisible());
    await user.click(
      within(confirmed).getByRole("button", { name: "Continue" }),
    );
    await waitFor(() => expect(kind).toHaveValue("Movie"));
    await waitFor(() => expect(kind).toHaveFocus());
    expect(
      screen.queryByRole("group", { name: "Season 1" }),
    ).not.toBeInTheDocument();
  });

  it("changes kind immediately when a new series has no hierarchy to discard", async () => {
    const user = userEvent.setup();
    renderEditor({
      initialDocument: keyed(createManualDocument("series", "en")),
    });

    const kind = screen.getByRole("combobox", { name: "Media kind" });
    await user.click(kind);
    await user.keyboard("{ArrowUp}{Enter}");

    expect(kind).toHaveValue("Movie");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("does not allow an open collection option to mutate state after review starts", async () => {
    const user = userEvent.setup();
    renderEditor({
      initialCollectionId: null,
      initialDocument: newSeriesDocument(),
    });

    const collection = screen.getByRole("combobox", { name: "Collection" });
    await user.click(collection);
    await waitFor(() =>
      expect(collection).toHaveAttribute("aria-expanded", "true"),
    );
    await user.keyboard("{ArrowDown}");
    const option = await screen.findByText("Favorites");
    const removeSeason = within(
      screen.getByRole("group", { name: "Season 1" }),
    ).getByRole("button", { name: "Remove season 1" });
    fireEvent.click(removeSeason);
    await screen.findByRole("dialog");
    fireEvent.click(option);

    expect(collection).toHaveValue("");
  });

  it("reports the first invalid field, focuses it, and submits valid editor state", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    renderEditor({
      initialCollectionId: "favorites",
      initialDocument: keyed(createManualDocument("movie", "en")),
      onSubmit,
    });

    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Enter a title.");
    expect(screen.getByLabelText("Title (English)")).toHaveFocus();
    expect(onSubmit).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Title (English)"), "New movie");
    await user.click(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    );

    expect(onSubmit).toHaveBeenCalledOnce();
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ titles: { en: "New movie" } }),
      "favorites",
    );
  });

  it("disables every structured editing control while its page owns an operation", () => {
    renderEditor({
      disabled: true,
      initialDocument: keyed(createManualDocument("series", "en")),
    });

    expect(screen.getByLabelText("Title (English)")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add season" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Save Manual metadata" }),
    ).toBeDisabled();
  });

  it("keeps exact raw list text through blur, clearing and retyping", async () => {
    const user = userEvent.setup();
    renderEditor({
      initialDocument: keyed(createManualDocument("movie", "en")),
    });
    await user.click(screen.getByRole("button", { name: "Additional fields" }));

    const genres = screen.getByLabelText("Genres");
    await user.type(genres, "Drama, Comedy, ");
    await user.tab();
    expect(genres).toHaveValue("Drama, Comedy, ");
    await user.clear(genres);
    expect(genres).toHaveValue("");
    await user.type(genres, "Drama, Comedy, ");
    expect(genres).toHaveValue("Drama, Comedy, ");
  });

  it("retains all raw lists across an interface-language rerender", async () => {
    const user = userEvent.setup();
    const view = renderEditor({
      initialDocument: keyed(createManualDocument("movie", "en")),
    });
    await user.click(screen.getByRole("button", { name: "Additional fields" }));
    const values = [
      ["Genres", "Drama, Comedy, "],
      ["Tags", "one, two, "],
      ["Countries", "US, CA, "],
      ["Studios", "North, South, "],
    ] as const;
    for (const [label, value] of values) {
      await user.type(screen.getByLabelText(label), value);
    }

    await view.i18n.changeLanguage("ru");
    for (const value of values.map(([, raw]) => raw)) {
      expect(screen.getAllByRole("textbox")).toContainEqual(
        expect.objectContaining({ value }),
      );
    }
  });
});
