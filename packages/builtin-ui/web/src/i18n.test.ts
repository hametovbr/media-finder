import { afterEach, describe, expect, it, vi } from "vitest";

import en from "./locales/en.json";
import ru from "./locales/ru.json";
import { createUiI18n } from "./i18n";

function leafKeys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) {
    return [prefix];
  }
  return Object.entries(value).flatMap(([key, child]) =>
    leafKeys(child, prefix.length === 0 ? key : `${prefix}.${key}`),
  );
}

describe("UI locale catalogs", () => {
  afterEach(() => vi.restoreAllMocks());
  it("keep English and Russian keys complete and deterministic", () => {
    expect(leafKeys(ru).sort()).toEqual(leafKeys(en).sort());
  });

  it("chooses the first supported primary browser language in order", () => {
    vi.spyOn(window.navigator, "languages", "get").mockReturnValue([
      "de-DE",
      "ru-RU",
      "en-US",
    ]);
    expect(createUiI18n().language).toBe("ru");
  });

  it("falls back to English when no supported language is present", () => {
    vi.spyOn(window.navigator, "languages", "get").mockReturnValue(["de-DE"]);
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("fr-FR");
    expect(createUiI18n().language).toBe("en");
  });

  it("uses navigator.language when languages is missing or empty", () => {
    vi.spyOn(window.navigator, "languages", "get").mockReturnValue([]);
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("ru-RU");
    expect(createUiI18n().language).toBe("ru");

    vi.spyOn(window.navigator, "languages", "get").mockReturnValue(
      undefined as unknown as readonly string[],
    );
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("en-GB");
    expect(createUiI18n().language).toBe("en");
  });

  it("provide localized messages for the invariant workflow error codes", () => {
    for (const code of [
      "confirmation_required",
      "csrf_invalid",
      "download_destination_unavailable",
      "internal_error",
      "media_item_not_found",
      "metadata_unavailable",
      "release_search_token_expired",
      "release_selection_invalid",
      "selection_expired",
      "session_invalid",
      "unexpected_response",
    ] as const) {
      expect(en.errors[code]).not.toBe(code);
      expect(ru.errors[code]).not.toBe(code);
    }
  });
});
