import { describe, expect, it } from "vitest";

import en from "./locales/en.json";
import ru from "./locales/ru.json";

function leafKeys(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) {
    return [prefix];
  }
  return Object.entries(value).flatMap(([key, child]) =>
    leafKeys(child, prefix.length === 0 ? key : `${prefix}.${key}`),
  );
}

describe("UI locale catalogs", () => {
  it("keep English and Russian keys complete and deterministic", () => {
    expect(leafKeys(ru).sort()).toEqual(leafKeys(en).sort());
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
