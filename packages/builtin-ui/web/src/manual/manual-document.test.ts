import { describe, expect, it } from "vitest";

import type { components } from "../api/control.generated";
import {
  createManualDocument,
  createManualRawLists,
  manualDraftEquals,
  manualDocumentFromItem,
  projectManualDocument,
  toManualDocument,
  withManualRowKeys,
} from "./manual-document";

type MediaItemDetail = components["schemas"]["MediaItemDetail"];

const richManualSeries = {
  acquisitions: [],
  archived: false,
  collection_id: "collection-1",
  external_id: "e0a465bb-34eb-4565-bde2-b80d6e789b7c",
  id: "manual-series",
  kind: "series",
  metadata: {
    artwork: [
      {
        kind: "poster",
        language: "en",
        url: "https://images.example.invalid/poster.jpg",
      },
    ],
    countries: ["DE"],
    genres: ["Mystery"],
    kind: "series",
    original_title: "A Manual Series",
    people: [
      { character: "The Archivist", name: "Example Actor", role: "cast" },
    ],
    plot: "A rich Manual series.",
    provider_ids: { tvdb: "fixture-42" },
    ratings: [{ source: "fixture", value: 9.2, votes: 42 }],
    release_date: "2025-01-02",
    runtime_minutes: 48,
    seasons: [
      {
        episodes: [
          {
            air_date: "2025-01-01",
            number: 1,
            ordering: 1,
            plot: "The special begins.",
            provider_ids: { tvdb: "special-1" },
            runtime_minutes: 12,
            title: "Special",
          },
        ],
        number: 0,
        plot: "Special presentations.",
        provider_ids: { tvdb: "specials" },
        title: "Specials",
      },
    ],
    studios: ["Fixture Television"],
    tags: ["manual", "rich"],
    titles: {
      en: "Manual Series",
      ru: "\u0420\u0443\u0447\u043d\u043e\u0439 \u0441\u0435\u0440\u0438\u0430\u043b",
    },
    year: 2025,
  },
  provider_key: "manual",
} satisfies MediaItemDetail;

describe("Manual document mapping", () => {
  it.each([
    ["movie", "en"],
    ["series", "ru"],
  ] as const)(
    "creates an identity-free %s document in the session metadata locale",
    (kind, locale) => {
      const document = createManualDocument(kind, locale);

      expect(document).toEqual({
        artwork: [],
        countries: [],
        genres: [],
        kind,
        locale,
        original_title: null,
        people: [],
        plot: null,
        provider_ids: {},
        ratings: [],
        release_date: null,
        runtime_minutes: null,
        schema_version: "1",
        seasons: [],
        studios: [],
        tags: [],
        titles: { [locale]: "" },
        year: null,
      });
      expect(document).not.toHaveProperty("external_id");
    },
  );

  it("maps a rich item without losing immutable identity, other locales, or Season 00", () => {
    const document = manualDocumentFromItem(richManualSeries, "ru");

    expect(document).toEqual({
      artwork: [
        {
          kind: "poster",
          language: "en",
          url: "https://images.example.invalid/poster.jpg",
        },
      ],
      countries: ["DE"],
      external_id: "e0a465bb-34eb-4565-bde2-b80d6e789b7c",
      genres: ["Mystery"],
      kind: "series",
      locale: "ru",
      original_title: "A Manual Series",
      people: [
        {
          character: "The Archivist",
          name: "Example Actor",
          role: "cast",
        },
      ],
      plot: "A rich Manual series.",
      provider_ids: { tvdb: "fixture-42" },
      ratings: [{ source: "fixture", value: 9.2, votes: 42 }],
      release_date: "2025-01-02",
      runtime_minutes: 48,
      schema_version: "1",
      seasons: [
        {
          episodes: [
            {
              air_date: "2025-01-01",
              number: 1,
              ordering: 1,
              plot: "The special begins.",
              provider_ids: { tvdb: "special-1" },
              runtime_minutes: 12,
              title: "Special",
            },
          ],
          number: 0,
          plot: "Special presentations.",
          provider_ids: { tvdb: "specials" },
          title: "Specials",
        },
      ],
      studios: ["Fixture Television"],
      tags: ["manual", "rich"],
      titles: {
        en: "Manual Series",
        ru: "\u0420\u0443\u0447\u043d\u043e\u0439 \u0441\u0435\u0440\u0438\u0430\u043b",
      },
      year: 2025,
    });
  });

  it("keeps stable season and episode row keys out of the submitted document", () => {
    const document = manualDocumentFromItem(richManualSeries, "en");
    const keys = ["season-key", "episode-key"];
    let keyIndex = 0;
    const editorDocument = withManualRowKeys(document, () => keys[keyIndex++]!);

    expect(
      [
        editorDocument.seasons[0]?.rowKey,
        editorDocument.seasons[0]?.episodes[0]?.rowKey,
      ].sort(),
    ).toEqual([...keys].sort());
    expect(toManualDocument(editorDocument)).toEqual(document);
  });

  it("normalizes only raw lists changed from their initial text and keeps rich metadata intact", () => {
    const document = manualDocumentFromItem(richManualSeries, "en");
    document.genres = ["Science, Fiction", "Drama"];
    const editorDocument = withManualRowKeys(document, () => "row-key");
    const initialRawLists = createManualRawLists(editorDocument);

    expect(
      projectManualDocument(editorDocument, initialRawLists, {
        ...initialRawLists,
        tags: "manual, updated, ",
      }),
    ).toEqual({
      ...document,
      genres: ["Science, Fiction", "Drama"],
      tags: ["manual", "updated"],
    });
    expect(
      projectManualDocument(editorDocument, initialRawLists, initialRawLists),
    ).toEqual(document);
    expect(
      projectManualDocument(editorDocument, initialRawLists, {
        ...initialRawLists,
        genres: "",
      }),
    ).toEqual({ ...document, genres: [] });
  });

  it("treats raw-list reverts as clean while excluding row keys and retaining shared collection state", () => {
    const document = manualDocumentFromItem(richManualSeries, "en");
    const initial = withManualRowKeys(document, () => "initial-row");
    const rerendered = withManualRowKeys(document, () => "rerendered-row");
    const rawLists = createManualRawLists(initial);

    expect(
      manualDraftEquals(
        initial,
        rerendered,
        rawLists,
        { ...rawLists, genres: "Mystery, " },
        "collection-1",
        "collection-1",
      ),
    ).toBe(false);
    expect(
      manualDraftEquals(
        initial,
        rerendered,
        rawLists,
        {
          tags: rawLists.tags,
          studios: rawLists.studios,
          genres: rawLists.genres,
          countries: rawLists.countries,
        },
        "collection-1",
        "collection-1",
      ),
    ).toBe(true);
    expect(
      manualDraftEquals(
        initial,
        rerendered,
        rawLists,
        rawLists,
        "collection-1",
        null,
      ),
    ).toBe(false);
  });
});
