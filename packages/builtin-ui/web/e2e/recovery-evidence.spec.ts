import { expect, test, type Page, type Route } from "@playwright/test";
import en from "../src/locales/en.json" assert { type: "json" };
import ru from "../src/locales/ru.json" assert { type: "json" };

type Locale = "en" | "ru";
type Scenario =
  | "bootstrap-failure"
  | "provider-discovery-failure"
  | "metadata-search-failure"
  | "metadata-search-empty"
  | "release-search-failure"
  | "release-search-empty"
  | "locale-update-failure"
  | "metadata-search-pending"
  | "metadata-keyboard-recovery";

const scenarios: readonly Scenario[] = [
  "bootstrap-failure",
  "provider-discovery-failure",
  "metadata-search-failure",
  "metadata-search-empty",
  "release-search-failure",
  "release-search-empty",
  "locale-update-failure",
  "metadata-search-pending",
  "metadata-keyboard-recovery",
];
const locales: readonly Locale[] = ["en", "ru"];
const widths = [360, 1280] as const;
const longQuery = "LongQuery".repeat(30);
const posterUrl = "http://127.0.0.1:4173/evidence-poster.svg";
const labels = { en, ru };

type Session = {
  csrf_token: string;
  metadata_locale: Locale;
  supported_locales: Locale[];
  ui_locale: Locale;
};
type MetadataSearch = {
  description: string;
  external_id: string;
  kind: "movie";
  locale: Locale;
  poster_url: string | null;
  provider_key: string;
  title: string;
  token: string;
  year: number;
};
type ErrorBody = { error: { code: string } };

const fixtureResult = (locale: Locale): MetadataSearch => ({
  description: "A deterministic browser evidence result.",
  external_id: "evidence-1",
  kind: "movie",
  locale,
  poster_url: posterUrl,
  provider_key: "fixture",
  title: "Evidence result",
  token: "evidence-token",
  year: 2026,
});

function copy<T>(value: T): T {
  return structuredClone(value);
}

async function fulfillJson(route: Route, json: unknown, status = 200) {
  await route.fulfill({ status, json });
}

async function configureFixtures(
  page: Page,
  locale: Locale,
  scenario: Scenario,
) {
  let sessionRequests = 0;
  let metadataRequests = 0;
  let resolvePending: (() => void) | undefined;
  let pendingResponse: Promise<void> | undefined;
  let pendingComplete: Promise<void> | undefined;
  const session: Session = {
    csrf_token: "csrf-evidence",
    metadata_locale: locale,
    supported_locales: ["en", "ru"],
    ui_locale: locale,
  };

  await page.route("**/*", async (route, request) => {
    if (new URL(request.url()).origin !== "http://127.0.0.1:4173") {
      await route.abort("blockedbyclient");
      return;
    }
    await route.fallback();
  });

  await page.route("**/evidence-poster.svg", (route) =>
    route.fulfill({
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="3"/>',
      contentType: "image/svg+xml",
    }),
  );
  await page.route("**/api/control/v1/session", async (route, request) => {
    sessionRequests += 1;
    if (
      scenario === "bootstrap-failure" &&
      request.method() === "GET" &&
      sessionRequests === 1
    ) {
      await fulfillJson(
        route,
        { error: { code: "internal_error" } } satisfies ErrorBody,
        503,
      );
      return;
    }
    if (request.method() === "PATCH" && scenario === "locale-update-failure") {
      await fulfillJson(route, { error: { code: "internal_error" } }, 503);
      return;
    }
    await fulfillJson(route, copy(session));
  });
  await page.route("**/api/control/v1/collections**", (route) =>
    fulfillJson(route, { items: [], next_cursor: null }),
  );
  await page.route(/\/api\/control\/v1\/media-items(?:\?.*)?$/, (route) =>
    fulfillJson(route, { items: [], next_cursor: null }),
  );
  await page.route(
    /\/api\/control\/v1\/media-items\/item-evidence(?:\?.*)?$/,
    (route) =>
      fulfillJson(route, {
        acquisitions: [],
        archived: false,
        collection_id: null,
        external_id: "evidence-item",
        id: "item-evidence",
        kind: "movie",
        metadata: {
          artwork: [],
          countries: [],
          genres: [],
          kind: "movie",
          original_title: null,
          people: [],
          plot: null,
          ratings: [],
          seasons: [],
          studios: [],
          tags: [],
          titles: {
            en: "Evidence item",
            ru: "\u041f\u0440\u043e\u0438\u0437\u0432\u0435\u0434\u0435\u043d\u0438\u0435",
          },
          year: 2026,
        },
        provider_key: "fixture",
      }),
  );
  await page.route("**/api/control/v1/metadata-providers", async (route) => {
    if (scenario === "provider-discovery-failure") {
      await fulfillJson(
        route,
        {
          error: { code: "metadata_provider_unavailable" },
        } satisfies ErrorBody,
        503,
      );
      return;
    }
    await fulfillJson(route, [
      {
        capabilities: ["search", "select"],
        key: "fixture",
        name_key: "tmdb.name",
        ready: true,
      },
    ]);
  });
  await page.route("**/api/control/v1/metadata-searches", async (route) => {
    metadataRequests += 1;
    if (scenario === "metadata-search-pending") {
      pendingResponse = new Promise<void>((resolve) => {
        resolvePending = resolve;
      });
      pendingComplete = pendingResponse.then(() =>
        fulfillJson(route, [fixtureResult(locale)]),
      );
      await pendingResponse;
      await pendingComplete;
      return;
    }
    if (scenario === "metadata-keyboard-recovery" && metadataRequests === 1) {
      await fulfillJson(
        route,
        { error: { code: "internal_error" } } satisfies ErrorBody,
        503,
      );
      return;
    }
    if (scenario === "metadata-search-failure") {
      await fulfillJson(
        route,
        { error: { code: "internal_error" } } satisfies ErrorBody,
        503,
      );
      return;
    }
    await fulfillJson(
      route,
      scenario === "metadata-search-empty" ? [] : [fixtureResult(locale)],
    );
  });
  await page.route("**/api/control/v1/metadata-selections/*", (route) =>
    fulfillJson(
      route,
      {
        acquisitions: [],
        archived: false,
        collection_id: null,
        external_id: "evidence-selected",
        id: "evidence-selected",
        kind: "movie",
        metadata: {
          artwork: [],
          countries: [],
          genres: [],
          kind: "movie",
          original_title: null,
          people: [],
          plot: "A deterministic selected fixture.",
          ratings: [],
          seasons: [],
          studios: [],
          tags: [],
          titles: {
            en: "Evidence result",
            ru: "\u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438",
          },
          year: 2026,
        },
        provider_key: "fixture",
      },
      201,
    ),
  );
  await page.route(
    "**/api/control/v1/media-items/*/release-searches",
    async (route) => {
      if (scenario === "release-search-failure") {
        await fulfillJson(
          route,
          { error: { code: "internal_error" } } satisfies ErrorBody,
          503,
        );
        return;
      }
      await fulfillJson(route, scenario === "release-search-empty" ? [] : []);
    },
  );

  return {
    settle: () => {
      resolvePending?.();
      return pendingComplete ?? pendingResponse;
    },
  };
}

async function disableMotionAndWait(page: Page) {
  await page.addStyleTag({
    content:
      "*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }",
  });
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      Array.from(document.images, (image) =>
        image.complete
          ? Promise.resolve()
          : new Promise<void>((resolve) => {
              image.addEventListener("load", () => resolve(), { once: true });
              image.addEventListener("error", () => resolve(), { once: true });
            }),
      ),
    );
  });
}

async function assertNoOverflow(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
}

async function assertRecoveryControls(page: Page, locale: Locale) {
  const t = labels[locale];
  const controls = page
    .getByRole("button", { name: t.recovery.retry, exact: true })
    .or(page.getByRole("link", { name: t.metadata.chooseManual, exact: true }));
  for (const control of await controls.all()) {
    await expect(control).toBeVisible();
    for (const hovered of [false, true]) {
      await page.mouse.move(0, 0);
      if (hovered) await control.hover();
      const metrics = await control.evaluate((element) => {
        const rgb = (value: string) => value.match(/[\d.]+/g)!.map(Number);
        const over = (front: number[], back: number[]) => {
          const alpha = front[3] ?? 1;
          return back
            .slice(0, 3)
            .map(
              (channel, index) => front[index] * alpha + channel * (1 - alpha),
            );
        };
        const background = (node: Element | null): number[] =>
          node
            ? over(
                rgb(getComputedStyle(node).backgroundColor),
                background(node.parentElement),
              )
            : [255, 255, 255];
        const luminance = (channels: number[]) => {
          const linear = channels.map((channel) => {
            const value = channel / 255;
            return value <= 0.04045
              ? value / 12.92
              : ((value + 0.055) / 1.055) ** 2.4;
          });
          return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
        };
        const bg = background(element);
        const fg = over(rgb(getComputedStyle(element).color), bg);
        const light = Math.max(luminance(bg), luminance(fg));
        const dark = Math.min(luminance(bg), luminance(fg));
        const box = element.getBoundingClientRect();
        const label = element.querySelector(".mantine-Button-label")!;
        return {
          contrast: (light + 0.05) / (dark + 0.05),
          width: box.width,
          height: box.height,
          labelFits:
            label.scrollWidth <= label.clientWidth + 1 &&
            label.scrollHeight <= label.clientHeight + 1,
        };
      });
      expect(
        metrics.contrast,
        "recovery control text contrast",
      ).toBeGreaterThanOrEqual(4.5);
      expect(metrics.width, "recovery target width").toBeGreaterThanOrEqual(24);
      expect(metrics.height, "recovery target height").toBeGreaterThanOrEqual(
        24,
      );
      expect(metrics.labelFits, "unclipped recovery control label").toBe(true);
    }
  }
  await page.mouse.move(0, 0);
}

async function exercise(page: Page, locale: Locale, scenario: Scenario) {
  const t = labels[locale];
  if (scenario === "bootstrap-failure") {
    await page.goto("/add");
    await expect(
      page.getByRole("heading", { name: t.bootstrap.title }),
    ).toBeVisible();
    return;
  }
  if (scenario === "locale-update-failure") {
    await page.goto("/add");
    const switchLabel =
      locale === "en"
        ? labels.en.locale.switchToRussian
        : labels.ru.locale.switchToEnglish;
    await page.getByRole("button", { name: switchLabel }).click();
    await expect(page.getByRole("alert")).toContainText(t.locale.failed);
    return;
  }
  if (scenario.startsWith("release-")) {
    await page.goto("/items/item-evidence/releases");
    const input = page.getByRole("searchbox", { name: t.release.query });
    await expect(
      page.getByText(t.release.contextLabel, { exact: true }),
    ).toBeVisible();
    await expect(input).toHaveValue(/\S+/);
    await input.fill(longQuery);
    await page.getByRole("button", { name: t.release.search }).click();
    await expect(
      scenario === "release-search-failure"
        ? page.getByRole("button", { name: t.recovery.retry })
        : page.getByText(t.search.empty.replace("{{query}}", longQuery)),
    ).toBeVisible();
    await assertNoOverflow(page);
    return;
  }
  await page.goto("/add");
  await page.getByRole("button", { name: t.metadata.chooseProvider }).click();
  if (scenario === "provider-discovery-failure") {
    await expect(
      page.getByRole("button", { name: t.recovery.retry }),
    ).toBeVisible();
    return;
  }
  const input = page.getByRole("searchbox", { name: t.metadata.title });
  await input.fill(longQuery);
  const search = page.getByRole("button", { name: t.metadata.search });
  await search.click();
  if (scenario === "metadata-search-pending") {
    await expect(page.getByRole("status")).toContainText(
      t.search.pending.replace("{{query}}", longQuery),
    );
    await assertNoOverflow(page);
    return;
  }
  if (scenario === "metadata-keyboard-recovery") {
    await expect(
      page.getByRole("button", { name: t.recovery.retry }),
    ).toBeVisible();
    await page.getByRole("button", { name: t.recovery.retry }).focus();
    await page.keyboard.press("Enter");
    const row = page.getByRole("article", { name: /Evidence result/ });
    await expect(row).toBeVisible();
    await search.focus();
    await page.keyboard.press("Tab");
    await expect(
      row.getByRole("button", { name: t.metadata.select }),
    ).toBeFocused();
    await expect(
      row.getByRole("button", { name: t.metadata.select }),
    ).toHaveCSS("outline-style", "solid");
  } else if (scenario === "metadata-search-failure") {
    await expect(
      page.getByRole("button", { name: t.recovery.retry }),
    ).toBeVisible();
  } else {
    await expect(
      page.getByText(t.search.empty.replace("{{query}}", longQuery)),
    ).toBeVisible();
  }
  await assertNoOverflow(page);
}

for (const scenario of scenarios) {
  for (const locale of locales) {
    for (const width of widths) {
      test(`${scenario} ${locale} ${width}`, async ({ page }, testInfo) => {
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
        const unexpected: string[] = [];
        page.on("request", (request) => {
          const url = new URL(request.url());
          if (url.origin !== "http://127.0.0.1:4173")
            unexpected.push(request.url());
        });
        const fixtures = await configureFixtures(page, locale, scenario);
        try {
          await exercise(page, locale, scenario);
          await disableMotionAndWait(page);
          await assertNoOverflow(page);
          await assertRecoveryControls(page, locale);
          const path = testInfo.outputPath(
            `${scenario}-${locale}-${width}.png`,
          );
          await page.screenshot({ path, fullPage: true });
          await testInfo.attach(`${scenario}-${locale}-${width}`, {
            path,
            contentType: "image/png",
          });
          expect(unexpected, "unexpected external traffic").toEqual([]);
        } finally {
          await fixtures.settle();
        }
      });
    }
  }
}
