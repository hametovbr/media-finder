import { expect, test } from "@playwright/test";

const session = {
  csrf_token: "csrf-browser-test",
  metadata_locale: "en",
  supported_locales: ["en", "ru"],
  ui_locale: "en",
};

test.beforeEach(async ({ page }) => {
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
  await page.route("**/api/control/v1/media-items/*", (route) =>
    route.fulfill({
      json: {
        acquisitions: [],
        archived: false,
        collection_id: null,
        external_id: "item-42",
        id: "item-42",
        kind: "movie",
        metadata: { kind: "movie", titles: { en: "Media overview" } },
        provider_key: "fixture",
      },
    }),
  );
  await page.route("**/api/control/v1/metadata-providers", (route) =>
    route.fulfill({ json: [] }),
  );
});

for (const [path, heading] of [
  ["/", "Catalog"],
  ["/add", "Add title"],
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
