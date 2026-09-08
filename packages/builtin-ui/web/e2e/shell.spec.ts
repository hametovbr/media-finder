import { expect, test, type Page, type TestInfo } from "@playwright/test";
import en from "../src/locales/en.json" assert { type: "json" };
import ru from "../src/locales/ru.json" assert { type: "json" };

type UiLocale = "en" | "ru";
const localeCatalogs = { en, ru } as const;

const session = {
  csrf_token: "csrf-browser-test",
  metadata_locale: "en",
  supported_locales: ["en", "ru"],
  ui_locale: "en",
};
const detailPosterUrl = "http://127.0.0.1:4173/detail-poster.jpg";
let savedManual: ReturnType<typeof manualItem> | null = null;

async function attachManualScreenshot(
  page: Page,
  testInfo: TestInfo,
  scenario: string,
  locale: UiLocale,
  width: number,
) {
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  const path = testInfo.outputPath(`${scenario}-${locale}-${width}.png`);
  await page.screenshot({ path, fullPage: true });
  await testInfo.attach(`${scenario}-${locale}-${width}`, {
    path,
    contentType: "image/png",
  });
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
}

function manualItem(kind: "movie" | "series", title: string) {
  return {
    acquisitions: [],
    archived: false,
    collection_id: null,
    external_id: `manual-${kind}-identity`,
    id: `manual-${kind}`,
    kind,
    metadata: {
      artwork: [{ kind: "poster", url: detailPosterUrl }],
      countries: [],
      genres: [" Mystery ", " ", "Drama"],
      kind,
      original_title: `${title} original`,
      people: [],
      plot: `A deterministic ${kind} detail.`,
      ratings: [],
      seasons:
        kind === "series"
          ? [{ episodes: [{ number: 1, title: "Special" }], number: 0 }]
          : [],
      studios: [],
      tags: [],
      titles: { en: title, ru: title },
      year: 2026,
    },
    provider_key: "manual",
  };
}

test.beforeEach(async ({ page }) => {
  savedManual = null;
  await page.route("**/api/control/v1/session", async (route, request) => {
    if (request.method() === "PATCH") {
      const update = request.postDataJSON() as { ui_locale?: string };
      await route.fulfill({
        json: { ...session, ui_locale: update.ui_locale ?? "en" },
      });
      return;
    }
    await route.fulfill({ json: session });
  });
  await page.route("**/api/control/v1/collections**", (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route(/\/api\/control\/v1\/media-items(?:\?.*)?$/, (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route("**/api/control/v1/media-items/*", (route, request) => {
    const itemId = new URL(request.url()).pathname.split("/").at(-1);
    const item =
      savedManual?.id === itemId
        ? savedManual
        : itemId?.startsWith("manual-")
          ? manualItem(
              itemId.includes("series") ? "series" : "movie",
              itemId.includes("series") ? "Manual Series" : "Manual Movie",
            )
          : {
              acquisitions: [],
              archived: false,
              collection_id: null,
              external_id: "item-42",
              id: "item-42",
              kind: "movie",
              metadata: {
                artwork: [
                  {
                    kind: "backdrop",
                    url: "https://images.example.invalid/backdrop.jpg",
                  },
                  { kind: "POSTER", url: detailPosterUrl },
                ],
                countries: [],
                genres: [" Science Fiction ", " ", "Drama"],
                kind: "movie",
                original_title: "Media overview original",
                people: [],
                plot: "A deterministic provider detail.",
                ratings: [],
                seasons: [],
                studios: [],
                tags: [],
                titles: { en: "Media overview" },
                year: 2024,
              },
              provider_key: "fixture",
            };
    return route.fulfill({ json: item });
  });
  await page.route("**/api/control/v1/metadata-providers", (route) =>
    route.fulfill({
      json: [
        {
          capabilities: ["search", "select"],
          key: "tmdb",
          name_key: "tmdb.name",
          ready: true,
        },
      ],
    }),
  );
  await page.route("**/api/control/v1/metadata-searches", (route) =>
    route.fulfill({
      json: [
        {
          description: "A deterministic browser preview.",
          external_id: "329865",
          kind: "movie",
          locale: "en",
          poster_url: "http://127.0.0.1:4173/poster-failure.jpg",
          provider_key: "tmdb",
          title: "Arrival",
          token: "metadata-token-browser",
          year: 2016,
        },
      ],
    }),
  );
  await page.route("**/api/control/v1/metadata-selections/*", (route) =>
    route.fulfill({ json: manualItem("movie", "Arrival"), status: 201 }),
  );
  await page.route(
    "**/api/control/v1/manual-imports",
    async (route, request) => {
      const body = request.postDataJSON() as {
        document: {
          external_id?: string;
          kind: "movie" | "series";
          titles: { en?: string };
        };
      };
      if (body.document.external_id?.startsWith("duplicate")) {
        await route.fulfill({
          status: 409,
          json: {
            error: {
              code: "confirmation_required",
              details: {
                confirmation_token:
                  body.document.external_id === "duplicate-expired"
                    ? "expired-e2e"
                    : "opaque-e2e",
                kind: "manual",
              },
            },
          },
        });
        return;
      }
      savedManual = manualItem(
        body.document.kind,
        body.document.titles.en ?? "Manual item",
      );
      await route.fulfill({
        status: 201,
        json: savedManual,
      });
    },
  );
  await page.route(
    "**/api/control/v1/manual-imports/*/confirm",
    (route, request) => {
      if (request.url().includes("expired-e2e")) {
        return route.fulfill({
          status: 410,
          json: { error: { code: "selection_expired" } },
        });
      }
      savedManual = manualItem("movie", "Confirmed Manual");
      return route.fulfill({ json: savedManual });
    },
  );
  await page.route(
    "**/api/control/v1/media-items/*/episode-imports",
    async (route, request) => {
      const body = request.postDataJSON() as { csv: string };
      if (body.csv.includes("INVALID")) {
        return route.fulfill({
          status: 422,
          json: { error: { code: "episode_csv_invalid" } },
        });
      }
      savedManual = manualItem("series", "CSV revision");
      return route.fulfill({ json: savedManual });
    },
  );
  await page.route(
    "**/api/control/v1/media-items/*/manual-metadata",
    async (route, request) => {
      const document = request.postDataJSON() as {
        kind: "movie" | "series";
        titles: { en?: string };
      };
      savedManual = manualItem(
        document.kind,
        document.titles.en ?? "Edited Manual",
      );
      return route.fulfill({ json: savedManual });
    },
  );
});

for (const [path, heading] of [
  ["/", "Catalog"],
  ["/add", "Add title"],
  ["/add/manual", "Manual metadata"],
  ["/items/item-42", "Media overview"],
  ["/items/item-42/releases", "Find release"],
] as const) {
  test(`renders ${path} as a client route`, async ({ page }) => {
    await page.goto(path);
    await expect(
      page.getByRole("heading", { level: 1, name: heading }),
    ).toBeVisible();
  });
}

test("creates structured Manual metadata without processor traffic", async ({
  page,
}) => {
  const requests: string[] = [];
  page.on("request", (request) =>
    requests.push(new URL(request.url()).pathname),
  );
  await page.goto("/add/manual");
  await page.getByLabel("Title (English)").fill("Browser Manual");
  await page.getByRole("button", { name: "Save Manual metadata" }).click();
  await expect(
    page.getByRole("heading", { name: "Browser Manual" }),
  ).toBeVisible();
  expect(requests.some((path) => path.startsWith("/api/v1"))).toBe(false);
});

test("rich provider and Manual detail preserve exact poster metadata and actions", async ({
  page,
}) => {
  await page.route("**/detail-poster.jpg", (route) =>
    route.fulfill({
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="3"/>',
      contentType: "image/svg+xml",
    }),
  );

  await page.goto("/items/item-42");
  const providerPoster = page.getByRole("img", {
    name: "Poster for Media overview",
  });
  await expect(providerPoster).toBeVisible();
  await expect(providerPoster).toHaveAttribute("src", detailPosterUrl);
  await expect(providerPoster).toHaveAttribute("loading", "lazy");
  await expect(providerPoster).toHaveAttribute("referrerpolicy", "no-referrer");
  await expect(page.getByText("Original title")).toBeVisible();
  await expect(page.getByText("Media overview original")).toBeVisible();
  await expect(page.getByText("Science Fiction")).toBeVisible();
  await expect(page.getByText("Drama")).toBeVisible();
  await expect(page.getByRole("link", { name: "Find release" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Edit Manual metadata" }),
  ).toBeHidden();

  await page.goto("/items/manual-movie");
  await expect(
    page.getByRole("img", { name: "Poster for Manual Movie" }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Edit Manual metadata" }),
  ).toBeVisible();
});

test("failed detail poster falls back locally without mobile overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/detail-poster.jpg", (route) => route.abort());

  await page.goto("/items/item-42");
  await expect(
    page.getByRole("img", { name: "Poster unavailable for Media overview" }),
  ).toBeVisible();
  await expect(page.getByText("Media overview original")).toBeVisible();
  await expect(page.getByText("Science Fiction")).toBeVisible();
  await expect(page.getByRole("link", { name: "Find release" })).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
});

test("bookmarked Manual edit renders nested Season 00 controls", async ({
  page,
}) => {
  await page.goto("/items/manual-series/edit");
  await expect(
    page.getByRole("heading", { name: "Edit Manual metadata" }),
  ).toBeVisible();
  await expect(page.getByRole("group", { name: "Season 0" })).toBeVisible();
  await expect(
    page.getByRole("textbox", { name: "Episode CSV" }),
  ).toBeVisible();
  await page.getByLabel("Title (English)").fill("Edited Season 00 series");
  await page.getByRole("button", { name: "Save Manual metadata" }).click();
  await expect(
    page.getByRole("heading", { name: "Edited Season 00 series" }),
  ).toBeVisible();
});

test("duplicate JSON confirmation expiry retains input and never replays", async ({
  page,
}) => {
  let importRequests = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname.endsWith("/manual-imports")
    ) {
      importRequests += 1;
    }
  });
  const document = JSON.stringify({
    artwork: [],
    countries: [],
    external_id: "duplicate-expired",
    genres: [],
    kind: "movie",
    locale: "en",
    people: [],
    ratings: [],
    schema_version: "1",
    seasons: [],
    studios: [],
    tags: [],
    titles: { en: "Duplicate JSON" },
  });
  await page.goto("/add/manual");
  await page.getByRole("button", { name: "Complete JSON" }).click();
  await page.getByRole("textbox", { name: "Manual JSON" }).fill(document);
  await page.getByRole("button", { name: "Import Manual JSON" }).click();
  await page.getByRole("button", { name: "Confirm revision" }).click();

  await expect(page.getByRole("alert")).toContainText(
    "The selection expired. Submit the Manual document again.",
  );
  await expect(page.getByRole("textbox", { name: "Manual JSON" })).toHaveValue(
    document,
  );
  expect(importRequests).toBe(1);
  await expect(
    page.getByRole("dialog", { name: "Confirm Manual revision" }),
  ).toBeHidden();
});

test("episode CSV success and atomic failure use the control boundary", async ({
  page,
}) => {
  await page.goto("/items/manual-series/edit");
  await page
    .getByRole("textbox", { name: "Episode CSV" })
    .fill("season_number,episode_number,title\n0,2,Second special\n");
  await page.getByRole("button", { name: "Import episode CSV" }).click();
  await expect(
    page.getByRole("heading", { name: "CSV revision" }),
  ).toBeVisible();

  savedManual = null;
  await page.goto("/items/manual-series/edit");
  await page.getByRole("textbox", { name: "Episode CSV" }).fill("INVALID");
  await page.getByRole("button", { name: "Import episode CSV" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "The episode CSV is invalid; no episodes were changed.",
  );
  await expect(page.getByLabel("Title (English)")).toHaveValue("Manual Series");
});

test("Manual raw list typing stays visible across modes and normalizes on submit", async ({
  page,
}) => {
  let submitted: {
    collection_id: string | null;
    document: ReturnType<typeof manualItem>["metadata"] & {
      kind: "movie" | "series";
      locale: "en" | "ru";
      schema_version: string;
      titles: { en?: string; ru?: string };
    };
  } | null = null;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/control/v1/manual-imports"
    ) {
      submitted = request.postDataJSON() as typeof submitted;
    }
  });

  await page.goto("/add/manual");
  await page.getByLabel("Title (English)").fill("Raw browser title");
  await page.getByRole("button", { name: "Additional fields" }).click();
  const rawLists = {
    Countries: "US, CA, ",
    Genres: "Drama, Comedy, ",
    Studios: "North, South, ",
    Tags: "one, two, ",
  } as const;
  for (const [label, value] of Object.entries(rawLists)) {
    await page.getByLabel(label).fill(value);
  }

  await page.getByRole("button", { name: "Complete JSON" }).click();
  await page.getByRole("button", { name: "Structured entry" }).click();
  await page.getByRole("button", { name: "Additional fields" }).click();
  for (const [label, value] of Object.entries(rawLists)) {
    await expect(page.getByLabel(label)).toHaveValue(value);
  }

  await page.getByRole("button", { name: "Save Manual metadata" }).click();
  await expect(
    page.getByRole("heading", { name: "Raw browser title" }),
  ).toBeVisible();
  expect(submitted).toMatchObject({
    collection_id: null,
    document: {
      countries: ["US", "CA"],
      genres: ["Drama", "Comedy"],
      studios: ["North", "South"],
      tags: ["one", "two"],
      titles: { en: "Raw browser title" },
    },
  });
});

test("Manual create keeps one delayed request and blocks competing actions", async ({
  page,
}) => {
  await page.unroute("**/api/control/v1/manual-imports");
  let requestCount = 0;
  let submitted: Record<string, unknown> | null = null;
  let releaseRequest: (() => void) | undefined;
  await page.route(
    "**/api/control/v1/manual-imports",
    async (route, request) => {
      requestCount += 1;
      submitted = request.postDataJSON() as Record<string, unknown>;
      await new Promise<void>((resolve) => {
        releaseRequest = resolve;
      });
      savedManual = manualItem("movie", "Delayed Manual");
      await route.fulfill({ status: 201, json: savedManual });
    },
  );

  await page.goto("/add/manual");
  await page.getByLabel("Title (English)").fill("Delayed Manual");
  const save = page.getByRole("button", { name: "Save Manual metadata" });
  await save.click();
  await expect(save).toBeDisabled();
  await expect(page.getByRole("status")).toContainText(
    "Saving Manual metadata…",
  );

  await save.dispatchEvent("click");
  await page
    .getByRole("button", { name: "Complete JSON" })
    .dispatchEvent("click");
  await page.getByRole("link", { name: "Catalog" }).first().click();
  await expect(page).toHaveURL(/\/add\/manual$/);
  expect(requestCount).toBe(1);
  expect(submitted).toMatchObject({
    document: { titles: { en: "Delayed Manual" } },
  });

  releaseRequest?.();
  await expect(
    page.getByRole("heading", { name: "Delayed Manual" }),
  ).toBeVisible();
});

test("Manual destructive removal requires review, preserves cancel, and confirms the exact target", async ({
  page,
}) => {
  await page.goto("/items/manual-series/edit");
  const removeSeason = page.getByRole("button", { name: "Remove season 0" });
  await removeSeason.click();
  const dialog = page.getByRole("dialog", { name: "Remove season 0?" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Remove season 0 and its 1 episodes?");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("group", { name: "Season 0" })).toBeVisible();
  await expect(removeSeason).toBeFocused();

  await removeSeason.click();
  const confirmDialog = page.getByRole("dialog", {
    name: "Remove season 0?",
  });
  await expect(confirmDialog).toBeVisible();
  await confirmDialog.getByRole("button", { name: "Continue" }).click();
  await expect(confirmDialog).toBeHidden();
  await expect(page.getByText("Seasons: 0 · Episodes: 0")).toBeVisible();
  await expect(page.getByRole("button", { name: "Add season" })).toBeFocused();
});

test("Manual dirty navigation offers Stay first and discards only after explicit leave", async ({
  page,
}) => {
  await page.goto("/items/manual-series/edit");
  const title = page.getByLabel("Title (English)");
  await title.fill("Unsaved browser title");

  const catalog = page.getByRole("link", { name: "Catalog" }).first();
  await catalog.click();
  const dialog = page.getByRole("dialog", { name: "Unsaved changes" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Stay" })).toBeFocused();
  await dialog.getByRole("button", { name: "Stay" }).click();
  await expect(dialog).toBeHidden();
  await expect(page).toHaveURL(/\/items\/manual-series\/edit$/);
  await expect(title).toHaveValue("Unsaved browser title");

  await catalog.click();
  const leaveDialog = page.getByRole("dialog", { name: "Unsaved changes" });
  await expect(leaveDialog).toBeVisible();
  await leaveDialog.getByRole("button", { name: "Discard and leave" }).click();
  await expect(page.getByRole("heading", { name: "Catalog" })).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
});

test("Manual add browser history blocks forward navigation until Stay or explicit leave", async ({
  page,
}) => {
  await page.goto("/add/manual");
  await expect(
    page.getByRole("heading", { name: "Manual metadata" }),
  ).toBeVisible();

  await page.getByRole("link", { name: "Catalog" }).first().click();
  await expect(page.getByRole("heading", { name: "Catalog" })).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("heading", { name: "Manual metadata" }),
  ).toBeVisible();

  await page.getByLabel("Title (English)").fill("Forward history draft");
  await page.goForward();
  const stayDialog = page.getByRole("dialog", { name: "Unsaved changes" });
  await expect(stayDialog).toBeVisible();
  await stayDialog.getByRole("button", { name: "Stay" }).click();
  await expect(stayDialog).toBeHidden();
  await expect(page).toHaveURL(/\/add\/manual$/);
  await expect(page.getByLabel("Title (English)")).toHaveValue(
    "Forward history draft",
  );

  await page.goForward();
  const leaveDialog = page.getByRole("dialog", { name: "Unsaved changes" });
  await expect(leaveDialog).toBeVisible();
  await leaveDialog.getByRole("button", { name: "Discard and leave" }).click();
  await expect(leaveDialog).toBeHidden();
  await expect(page.getByRole("heading", { name: "Catalog" })).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
});

test("Manual alternate JSON review retains both drafts and continues only the structured request", async ({
  page,
}) => {
  const requests: Record<string, unknown>[] = [];
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/control/v1/manual-imports"
    ) {
      requests.push(request.postDataJSON() as Record<string, unknown>);
    }
  });
  const jsonDraft = JSON.stringify({
    artwork: [],
    countries: [],
    external_id: "alternate-json-draft",
    genres: [],
    kind: "movie",
    locale: "en",
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
    titles: { en: "JSON draft" },
    year: 2026,
  });

  await page.goto("/add/manual");
  await page.getByLabel("Title (English)").fill("Structured draft");
  await page.getByRole("button", { name: "Complete JSON" }).click();
  await page.getByLabel("Manual JSON").fill(jsonDraft);
  await page.getByRole("button", { name: "Structured entry" }).click();
  await expect(page.getByLabel("Title (English)")).toHaveValue(
    "Structured draft",
  );
  await page.getByRole("button", { name: "Save Manual metadata" }).click();

  const review = page.getByRole("dialog", { name: "Review unsaved draft" });
  await expect(review).toBeVisible();
  await expect(review).toContainText("the unsaved JSON text");
  expect(requests).toHaveLength(0);
  await review.getByRole("button", { name: "Cancel" }).click();
  await expect(review).toBeHidden();

  await page.getByRole("button", { name: "Complete JSON" }).click();
  await expect(page.getByLabel("Manual JSON")).toHaveValue(jsonDraft);
  await page.getByRole("button", { name: "Structured entry" }).click();
  await expect(page.getByLabel("Title (English)")).toHaveValue(
    "Structured draft",
  );
  await page.getByRole("button", { name: "Save Manual metadata" }).click();
  await expect(review).toBeVisible();
  await review.getByRole("button", { name: "Continue saving" }).click();

  await expect(
    page.getByRole("heading", { name: "Structured draft" }),
  ).toBeVisible();
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({
    document: { titles: { en: "Structured draft" } },
  });
  expect(JSON.stringify(requests[0])).not.toContain("alternate-json-draft");
});

test("Manual CSV blocking preserves both drafts through cancel and reset before one CSV request", async ({
  page,
}) => {
  let csvRequests = 0;
  let editRequests = 0;
  page.on("request", (request) => {
    if (request.method() !== "POST" && request.method() !== "PUT") return;
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith("/episode-imports")) csvRequests += 1;
    if (pathname.endsWith("/manual-metadata")) editRequests += 1;
  });

  const csv = "season_number,episode_number,title\n1,1,Blocked\n";
  await page.goto("/items/manual-series/edit");
  await page.getByLabel("Title (English)").fill("Dirty form");
  await page.getByLabel("Episode CSV").fill(csv);
  await page.getByRole("button", { name: "Import episode CSV" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Save the form first or discard its changes before importing CSV.",
  );
  await expect(
    page.getByRole("button", { name: "Discard form changes" }),
  ).toBeVisible();
  expect(csvRequests).toBe(0);
  expect(editRequests).toBe(0);

  const discardTrigger = page.getByRole("button", {
    name: "Discard form changes",
  });
  await discardTrigger.click();
  const resetReview = page.getByRole("dialog", {
    name: "Discard form changes?",
  });
  await expect(resetReview).toBeVisible();
  await resetReview.getByRole("button", { name: "Cancel" }).click();
  await expect(resetReview).toBeHidden();
  await expect(page.getByLabel("Title (English)")).toHaveValue("Dirty form");
  await expect(page.getByLabel("Episode CSV")).toHaveValue(csv);
  expect(csvRequests).toBe(0);
  expect(editRequests).toBe(0);

  await discardTrigger.click();
  await expect(resetReview).toBeVisible();
  await resetReview
    .getByRole("button", { name: "Discard form changes" })
    .click();
  await expect(resetReview).toBeHidden();
  await expect(page.getByLabel("Title (English)")).toHaveValue("Manual Series");
  await expect(page.getByLabel("Episode CSV")).toHaveValue(csv);
  expect(csvRequests).toBe(0);
  expect(editRequests).toBe(0);

  await page.getByRole("button", { name: "Import episode CSV" }).click();
  await expect(
    page.getByRole("heading", { name: "CSV revision" }),
  ).toBeVisible();
  expect(csvRequests).toBe(1);
  expect(editRequests).toBe(0);
});

test("Manual create remains localized and responsive in Russian", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/add/manual");
  await page
    .getByRole("button", { name: "\u0420\u0443\u0441\u0441\u043a\u0438\u0439" })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "\u0420\u0443\u0447\u043d\u044b\u0435 \u043c\u0435\u0442\u0430\u0434\u0430\u043d\u043d\u044b\u0435",
    }),
  ).toBeVisible();
  await expect(
    page.getByLabel(
      "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 (\u0430\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u0438\u0439)",
    ),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
});

test("metadata rows support keyboard focus, pending feedback, poster failure, and mobile width", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/poster-failure.jpg", (route) => route.abort());
  let selectionRequests = 0;
  await page.route("**/api/control/v1/metadata-selections/*", async (route) => {
    selectionRequests += 1;
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.fulfill({
      json: manualItem("movie", "Arrival"),
      status: 201,
    });
  });
  await page.goto("/add");
  await page.getByRole("button", { name: "Search metadata providers" }).click();
  await page.getByRole("searchbox", { name: "Title" }).fill("Arrival");
  const search = page.getByRole("button", { name: "Search" });
  await search.click();
  const row = page.getByRole("article", { name: /Arrival/ });
  await expect(
    row.getByRole("img", { name: "Poster unavailable for Arrival" }),
  ).toBeVisible();
  const select = row.getByRole("button", { name: "Select" });
  await search.focus();
  await page.keyboard.press("Tab");
  await expect(select).toBeFocused();
  await expect
    .poll(() =>
      select.evaluate((element) => getComputedStyle(element).outlineStyle),
    )
    .not.toBe("none");
  await page.keyboard.press("Enter");
  await expect(
    row.getByRole("status", { name: "Selecting Arrival" }),
  ).toBeVisible();
  await expect(select).toBeDisabled();
  await expect(
    page.getByRole("heading", { name: "Saved to catalog" }),
  ).toBeVisible();
  expect(selectionRequests).toBe(1);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
});

test("Russian metadata similarity confirmation uses its new token and recovers from expiry", async ({
  page,
}) => {
  const tokens: string[] = [];
  await page.route(
    "**/api/control/v1/metadata-selections/*",
    async (route, request) => {
      const token = new URL(request.url()).pathname.split("/").at(-1) ?? "";
      tokens.push(token);
      if (token === "metadata-token-browser") {
        await route.fulfill({
          status: 409,
          json: {
            error: {
              code: "confirmation_required",
              details: {
                confirmation_token: "metadata-confirmation-browser",
                kind: "similarity",
              },
            },
          },
        });
        return;
      }
      await route.fulfill({
        status: 410,
        json: { error: { code: "selection_expired" } },
      });
    },
  );
  await page.goto("/add");
  await page
    .getByRole("button", {
      name: "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
    })
    .click();
  await page
    .getByRole("button", {
      name: "\u041d\u0430\u0439\u0442\u0438 \u0443 \u0438\u0441\u0442\u043e\u0447\u043d\u0438\u043a\u043e\u0432 \u043c\u0435\u0442\u0430\u0434\u0430\u043d\u043d\u044b\u0445",
    })
    .click();
  await page
    .getByRole("searchbox", {
      name: "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435",
    })
    .fill("Arrival");
  await page
    .getByRole("button", { name: "\u041d\u0430\u0439\u0442\u0438" })
    .click();
  await page
    .getByRole("button", {
      name: "\u0412\u044b\u0431\u0440\u0430\u0442\u044c",
    })
    .click();
  await expect(
    page.getByRole("dialog", {
      name: "\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c \u043f\u043e\u0445\u043e\u0436\u0435\u0435 \u043f\u0440\u043e\u0438\u0437\u0432\u0435\u0434\u0435\u043d\u0438\u0435",
    }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c \u0432\u044b\u0431\u043e\u0440",
    })
    .click();
  await expect(page.getByRole("alert")).toContainText(
    "\u0421\u0440\u043e\u043a \u0432\u044b\u0431\u043e\u0440\u0430 \u0438\u0441\u0442\u0451\u043a. \u0412\u044b\u043f\u043e\u043b\u043d\u0438\u0442\u0435 \u043f\u043e\u0438\u0441\u043a \u0441\u043d\u043e\u0432\u0430.",
  );
  await expect(page.getByRole("article", { name: /Arrival/ })).toBeHidden();
  expect(tokens).toEqual([
    "metadata-token-browser",
    "metadata-confirmation-browser",
  ]);
});

test("desktop navigation remains visible", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(
    page.getByRole("navigation", { name: "Primary navigation" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open navigation" }),
  ).toBeHidden();
});

test("mobile navigation traps focus, restores it, and does not overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const menuButton = page.getByRole("button", { name: "Open navigation" });
  await menuButton.click();

  await expect(
    page.getByRole("dialog", { name: "Media Finder" }),
  ).toBeVisible();
  await expect(
    page.getByRole("navigation", { name: "Primary navigation" }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(menuButton).toBeFocused();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
});

test("unknown routes and locale switching are localized", async ({ page }) => {
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { name: "Page not found" }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
    })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "\u0421\u0442\u0440\u0430\u043d\u0438\u0446\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u0430",
    }),
  ).toBeVisible();
});

test("keyboard bootstrap retry keeps the requested route and recovers in English", async ({
  page,
}) => {
  await page.unroute("**/api/control/v1/session");
  let attempts = 0;
  await page.route("**/api/control/v1/session", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        json: { error: { code: "internal_error" } },
      });
      return;
    }
    await route.fulfill({ json: session });
  });
  await page.goto("/items/item-42/releases");
  await expect(
    page.getByRole("heading", { name: "Could not load Media Finder" }),
  ).toBeVisible();
  const retry = page.getByRole("button", { name: "Retry" });
  await retry.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", { name: "Find release" }),
  ).toBeVisible();
  await expect(page.locator("main")).toBeFocused();
  expect(attempts).toBe(2);
});

test("Russian bootstrap failure is retryable and adopts the returned English session", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "languages", {
      configurable: true,
      value: ["ru-RU", "en-US"],
    });
    Object.defineProperty(navigator, "language", {
      configurable: true,
      value: "ru-RU",
    });
  });
  await page.unroute("**/api/control/v1/session");
  let attempts = 0;
  await page.route("**/api/control/v1/session", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        json: { error: { code: "internal_error" } },
      });
      return;
    }
    await route.fulfill({ json: session });
  });
  await page.goto("/add");
  await expect(
    page.getByRole("heading", {
      name: "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c Media Finder",
    }),
  ).toBeVisible();
  await page
    .getByRole("button", {
      name: "\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c",
    })
    .click();
  await expect(page.getByRole("heading", { name: "Add title" })).toBeVisible();
  await expect(
    page.getByRole("button", {
      name: "\u0420\u0443\u0441\u0441\u043a\u0438\u0439",
    }),
  ).toBeVisible();
  expect(attempts).toBe(2);
});

test("provider discovery retry is keyboard accessible and preserves the Manual alternative", async ({
  page,
}) => {
  await page.unroute("**/api/control/v1/metadata-providers");
  let attempts = 0;
  await page.route("**/api/control/v1/metadata-providers", async (route) => {
    attempts += 1;
    if (attempts === 1) {
      await route.fulfill({
        status: 503,
        json: { error: { code: "metadata_provider_unavailable" } },
      });
      return;
    }
    await route.fulfill({
      json: [
        {
          capabilities: ["search", "select"],
          key: "tmdb",
          name_key: "tmdb.name",
          ready: true,
        },
      ],
    });
  });
  await page.goto("/add");
  await page.getByRole("button", { name: "Search metadata providers" }).click();
  const retry = page.getByRole("button", { name: "Retry" });
  await expect(retry).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Enter or import Manual metadata" }),
  ).toBeVisible();
  await retry.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("searchbox", { name: "Title" })).toBeVisible();
  expect(attempts).toBe(2);
});

test("metadata retry uses the failed snapshot while edited input stays available", async ({
  page,
}) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.unroute("**/api/control/v1/metadata-searches");
  const requests: string[] = [];
  await page.route(
    "**/api/control/v1/metadata-searches",
    async (route, request) => {
      const body = request.postDataJSON() as { query: string };
      requests.push(body.query);
      if (requests.length === 1) {
        await route.fulfill({
          status: 503,
          json: { error: { code: "internal_error" } },
        });
        return;
      }
      await route.fulfill({
        json: [
          {
            description: "Recovered result",
            external_id: "recovered",
            kind: "movie",
            locale: "en",
            poster_url: null,
            provider_key: "tmdb",
            title: body.query,
            token: "metadata-recovered",
            year: 2026,
          },
        ],
      });
    },
  );
  await page.goto("/add");
  await page.getByRole("button", { name: "Search metadata providers" }).click();
  const input = page.getByRole("searchbox", { name: "Title" });
  const longQuery = "LongQuery".repeat(30);
  await input.fill(longQuery);
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  await input.fill("edited query");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("article", { name: /LongQuery/ })).toBeVisible();
  expect(requests).toEqual([longQuery, longQuery]);
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await test.info().attach("metadata-long-query-360", {
    body: await page.screenshot(),
    contentType: "image/png",
  });
});

test("release retry keeps the submitted snapshot and ignores a late response after navigation", async ({
  page,
}) => {
  await page.unroute("**/api/control/v1/media-items/*/release-searches");
  let resolveLate: (() => void) | undefined;
  const requests: string[] = [];
  await page.route(
    "**/api/control/v1/media-items/*/release-searches",
    async (route, request) => {
      const body = request.postDataJSON() as { query: string };
      requests.push(body.query);
      if (requests.length === 1) {
        await route.fulfill({
          status: 503,
          json: { error: { code: "internal_error" } },
        });
        return;
      }
      await new Promise<void>((resolve) => {
        resolveLate = resolve;
      });
      await route.fulfill({ json: [] });
    },
  );
  await page.goto("/items/item-42/releases");
  const input = page.getByRole("searchbox", { name: "Release query" });
  await input.fill("Arrival");
  await page.getByRole("button", { name: "Search releases" }).click();
  await expect(page.getByRole("button", { name: "Retry" })).toBeVisible();
  await input.fill("Edited");
  await page.getByRole("button", { name: "Retry" }).click();
  await expect(page.getByRole("status")).toContainText("Arrival");
  await page.keyboard.press("Enter");
  expect(requests).toEqual(["Arrival", "Arrival"]);
  await page.getByRole("link", { name: "Catalog" }).first().click();
  resolveLate?.();
  await expect(page.getByRole("heading", { name: "Catalog" })).toBeVisible();
  expect(requests).toEqual(["Arrival", "Arrival"]);
});

test("failed locale update retains the Manual field until keyboard retry succeeds", async ({
  page,
}) => {
  await page.unroute("**/api/control/v1/session");
  let patchAttempts = 0;
  await page.route("**/api/control/v1/session", async (route, request) => {
    if (request.method() !== "PATCH") {
      await route.fulfill({ json: session });
      return;
    }
    patchAttempts += 1;
    if (patchAttempts === 1) {
      await route.fulfill({
        status: 503,
        json: { error: { code: "internal_error" } },
      });
      return;
    }
    await route.fulfill({ json: { ...session, ui_locale: "ru" } });
  });

  await page.goto("/add/manual");
  const title = page.getByLabel("Title (English)");
  await title.fill("Retained Manual title");
  await page
    .getByRole("button", { name: "\u0420\u0443\u0441\u0441\u043a\u0438\u0439" })
    .click();
  await expect(page.getByRole("alert")).toContainText(en.locale.failed);
  await expect(title).toHaveValue("Retained Manual title");
  const retry = page.getByRole("button", { name: "Retry" });
  await retry.focus();
  await page.keyboard.press("Enter");
  await expect(
    page.getByRole("heading", {
      name: "\u0420\u0443\u0447\u043d\u044b\u0435 \u043c\u0435\u0442\u0430\u0434\u0430\u043d\u043d\u044b\u0435",
    }),
  ).toBeVisible();
  await expect(
    page.getByLabel(
      "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 (\u0430\u043d\u0433\u043b\u0438\u0439\u0441\u043a\u0438\u0439)",
    ),
  ).toHaveValue("Retained Manual title");
  expect(patchAttempts).toBe(2);
});

type ManualEvidenceScenario =
  "secondary" | "destructive" | "dirty" | "alternate" | "csv-blocked";

const manualEvidenceScenarios: readonly ManualEvidenceScenario[] = [
  "secondary",
  "destructive",
  "dirty",
  "alternate",
  "csv-blocked",
];

const manualEvidenceWidths = [360, 1280] as const;

async function switchManualEvidenceLocale(page: Page, locale: UiLocale) {
  if (locale === "ru") {
    await page.getByRole("button", { name: en.locale.switchToRussian }).click();
    await expect(
      page.getByRole("button", { name: ru.locale.switchToEnglish }),
    ).toBeVisible();
  }
}

function localizedTitleLabel(locale: UiLocale) {
  const labels = localeCatalogs[locale];
  return labels.manual.fields.title.replace(
    "{{locale}}",
    labels.manual.locales.en,
  );
}

async function exerciseManualEvidenceScenario(
  page: Page,
  locale: UiLocale,
  scenario: ManualEvidenceScenario,
) {
  const labels = localeCatalogs[locale];
  if (scenario === "alternate") {
    await page.goto("/add/manual");
    await switchManualEvidenceLocale(page, locale);
    await page.getByRole("button", { name: labels.manual.modes.json }).click();
    await page.getByLabel(labels.manual.json.source).fill('{"alternate":true}');
    await page
      .getByRole("button", { name: labels.manual.modes.structured })
      .click();
    await page.getByLabel(localizedTitleLabel(locale)).fill("Alternate draft");
    await page.getByRole("button", { name: labels.manual.save }).click();
    const dialog = page.getByRole("dialog", {
      name: labels.manual.drafts.title,
    });
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: labels.manual.drafts.cancel }),
    ).toBeFocused();
    return;
  }

  await page.goto("/items/manual-series/edit");
  await switchManualEvidenceLocale(page, locale);

  if (scenario === "secondary") {
    await page
      .getByRole("button", { name: labels.manual.secondaryFields })
      .click();
    await expect(
      page.getByRole("button", { name: labels.manual.secondaryFields }),
    ).toHaveAttribute("aria-expanded", "true");
    for (const field of [
      labels.manual.fields.originalTitle,
      labels.manual.fields.releaseDate,
      labels.manual.fields.runtimeMinutes,
      labels.manual.fields.genres,
      labels.manual.fields.tags,
      labels.manual.fields.countries,
      labels.manual.fields.studios,
    ]) {
      await expect(page.getByLabel(field)).toBeVisible();
    }
    await expect(
      page.getByText(
        labels.manual.hierarchySummary
          .replace("{{seasons}}", "1")
          .replace("{{episodes}}", "1"),
      ),
    ).toBeVisible();
    return;
  }

  if (scenario === "destructive") {
    const removeSeasonLabel = labels.manual.season.remove.replace(
      "{{number}}",
      "0",
    );
    await page.getByRole("button", { name: removeSeasonLabel }).click();
    const dialog = page.getByRole("dialog", {
      name: labels.manual.destructive.removeSeasonTitle.replace(
        "{{number}}",
        "0",
      ),
    });
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: labels.manual.destructive.cancel }),
    ).toBeFocused();
    return;
  }

  if (scenario === "dirty") {
    await page.getByLabel(localizedTitleLabel(locale)).fill("Dirty draft");
    await page
      .getByRole("link", { name: labels.navigation.catalog })
      .first()
      .click();
    const dialog = page.getByRole("dialog", {
      name: labels.manual.navigation.title,
    });
    await expect(dialog).toBeVisible();
    await expect(
      dialog.getByRole("button", { name: labels.manual.navigation.stay }),
    ).toBeFocused();
    return;
  }

  await page.getByLabel(localizedTitleLabel(locale)).fill("CSV blocked");
  const csv = "season_number,episode_number,title\n1,1,Blocked\n";
  await page.getByLabel(labels.manual.csv.source).fill(csv);
  await page.getByRole("button", { name: labels.manual.csv.submit }).click();
  await expect(page.getByRole("alert")).toContainText(
    labels.manual.csv.unsaved,
  );
  await expect(
    page.getByRole("button", { name: labels.manual.csv.discardStructured }),
  ).toBeVisible();
  await expect(page.getByLabel(localizedTitleLabel(locale))).toHaveValue(
    "CSV blocked",
  );
  await expect(page.getByLabel(labels.manual.csv.source)).toHaveValue(csv);
}

for (const scenario of manualEvidenceScenarios) {
  for (const locale of ["en", "ru"] as const) {
    for (const width of manualEvidenceWidths) {
      test(`Manual ${scenario} evidence ${locale} ${width}`, async ({
        page,
      }, testInfo) => {
        await page.setViewportSize({ width, height: 800 });
        await page.addInitScript((requestedLocale) => {
          const language = requestedLocale === "ru" ? "ru-RU" : "en-US";
          Object.defineProperty(navigator, "language", {
            configurable: true,
            value: language,
          });
          Object.defineProperty(navigator, "languages", {
            configurable: true,
            value: [language, "en-US"],
          });
        }, locale);
        await exerciseManualEvidenceScenario(page, locale, scenario);
        await expectNoHorizontalOverflow(page);
        await attachManualScreenshot(
          page,
          testInfo,
          `manual-${scenario}`,
          locale,
          width,
        );
      });
    }
  }
}
