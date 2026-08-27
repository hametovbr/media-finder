import { MantineProvider } from "@mantine/core";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { I18nextProvider } from "react-i18next";
import { describe, expect, it, vi } from "vitest";

import type { components } from "../api/control.generated";
import { createUiI18n } from "../i18n";
import { manualSeriesDetail } from "../mocks/fixtures";
import {
  createManualDocument,
  type ManualEditorDocument,
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

function EditorHarness({
  initialCollectionId = null,
  initialDocument,
  onSubmit = () => undefined,
}: {
  initialCollectionId?: string | null;
  initialDocument: ManualEditorDocument;
  onSubmit?: (
    document: ManualEditorDocument,
    collectionId: string | null,
  ) => void;
}) {
  const [document, setDocument] = useState(initialDocument);
  const [collectionId, setCollectionId] = useState(initialCollectionId);

  return (
    <ManualEditor
      collectionId={collectionId}
      collections={collections}
      document={document}
      onCollectionIdChange={setCollectionId}
      onDocumentChange={setDocument}
      onSubmit={onSubmit}
    />
  );
}

function renderEditor(props: Parameters<typeof EditorHarness>[0]) {
  return render(
    <I18nextProvider i18n={createUiI18n("en")}>
      <MantineProvider>
        <EditorHarness {...props} />
      </MantineProvider>
    </I18nextProvider>,
  );
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

  it("adds and deliberately removes season and episode rows from the keyboard", async () => {
    const user = userEvent.setup();
    renderEditor({
      initialDocument: keyed(createManualDocument("series", "en")),
    });

    const addSeason = screen.getByRole("button", { name: "Add season" });
    addSeason.focus();
    await user.keyboard("{Enter}");

    const season = screen.getByRole("group", { name: "Season 1" });
    const addEpisode = within(season).getByRole("button", {
      name: "Add episode",
    });
    addEpisode.focus();
    await user.keyboard("{Enter}");
    expect(
      within(season).getByRole("group", { name: "Episode 1" }),
    ).toBeVisible();

    const removeEpisode = within(season).getByRole("button", {
      name: "Remove episode 1",
    });
    removeEpisode.focus();
    await user.keyboard("{Enter}");
    expect(
      within(season).queryByRole("group", { name: "Episode 1" }),
    ).not.toBeInTheDocument();

    const removeSeason = within(season).getByRole("button", {
      name: "Remove season 1",
    });
    removeSeason.focus();
    await user.keyboard("{Enter}");
    expect(
      screen.queryByRole("group", { name: "Season 1" }),
    ).not.toBeInTheDocument();
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
});
