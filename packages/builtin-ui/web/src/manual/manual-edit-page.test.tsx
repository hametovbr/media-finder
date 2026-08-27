import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
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

async function renderEdit(
  item: MediaItem,
  options?: {
    confirmManual?: (token: string) => Promise<MediaItem>;
    editManual?: (id: string, document: ManualDocument) => Promise<MediaItem>;
    importEpisodes?: (id: string, csv: string) => Promise<MediaItem>;
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
    getMediaItem: vi.fn().mockResolvedValue(item),
    importEpisodes: vi.fn(options?.importEpisodes ?? (async () => item)),
    listCollections: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  } as unknown as ControlClient;
  const router = createMemoryRouter(appRoutes, {
    initialEntries: [`/items/${item.id}/edit`],
  });
  render(
    <I18nextProvider i18n={createUiI18n("en")}>
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
  return { client, editManual, router };
}

describe("ManualEditPage", () => {
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
});
