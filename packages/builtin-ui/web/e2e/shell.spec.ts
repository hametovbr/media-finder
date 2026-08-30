import { expect, test } from "@playwright/test";

const session = {
  csrf_token: "csrf-browser-test",
  metadata_locale: "en",
  supported_locales: ["en", "ru"],
  ui_locale: "en",
};
let savedManual: ReturnType<typeof manualItem> | null = null;

function manualItem(kind: "movie" | "series", title: string) {
  return {
    acquisitions: [],
    archived: false,
    collection_id: null,
    external_id: `manual-${kind}-identity`,
    id: `manual-${kind}`,
    kind,
    metadata: {
      artwork: [],
      countries: [],
      genres: [],
      kind,
      people: [],
      ratings: [],
      seasons:
        kind === "series"
          ? [{ episodes: [{ number: 1, title: "Special" }], number: 0 }]
          : [],
      studios: [],
      tags: [],
      titles: { en: title, ru: title },
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
              metadata: { kind: "movie", titles: { en: "Media overview" } },
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
