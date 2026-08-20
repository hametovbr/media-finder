import { delay, http, HttpResponse } from "msw";

import {
  catalogItems,
  collections,
  downloadDestinations,
  mediaDetail,
  metadataProviders,
  metadataResults,
  releaseResults,
  acquisitions,
  safeError,
  sessions,
  type MockScenario,
} from "./fixtures";

const control = "/api/control";

function activeScenario(request: Request): MockScenario {
  const scenario = new URL(request.url).searchParams.get("scenario");
  const pageScenario = new URL(globalThis.location.href).searchParams.get(
    "scenario",
  );
  const selected = scenario ?? pageScenario;
  if (
    selected === "catalog" ||
    selected === "desktop" ||
    selected === "empty" ||
    selected === "error" ||
    selected === "loading" ||
    selected === "mobile" ||
    selected === "ru" ||
    selected === "workflow"
  ) {
    return selected;
  }
  return "catalog";
}

async function applyScenarioDelay(request: Request) {
  if (activeScenario(request) === "loading") {
    await delay(2_000);
  }
}

export const mockHandlers = [
  http.get(`${control}/v1/session`, async ({ request }) => {
    await applyScenarioDelay(request);
    return HttpResponse.json(
      activeScenario(request) === "ru" ? sessions.ru : sessions.en,
    );
  }),
  http.patch(`${control}/v1/session`, async ({ request }) => {
    const update = (await request.json()) as { ui_locale?: "en" | "ru" };
    return HttpResponse.json(
      update.ui_locale === "ru" ? sessions.ru : sessions.en,
    );
  }),
  http.get(`${control}/v1/collections`, ({ request }) =>
    HttpResponse.json({
      items: activeScenario(request) === "empty" ? [] : collections,
      next_cursor: null,
    }),
  ),
  http.get(`${control}/v1/media-items`, async ({ request }) => {
    await applyScenarioDelay(request);
    if (activeScenario(request) === "error") {
      return HttpResponse.json(safeError, { status: 410 });
    }
    return HttpResponse.json({
      items: activeScenario(request) === "empty" ? [] : catalogItems,
      next_cursor: null,
    });
  }),
  http.get(`${control}/v1/media-items/:itemId`, ({ params }) =>
    params.itemId === mediaDetail.id
      ? HttpResponse.json(mediaDetail)
      : HttpResponse.json(
          {
            error: {
              code: "media_item_not_found",
              request_id: "mock-request-2",
            },
          },
          { status: 404 },
        ),
  ),
  http.get(`${control}/v1/metadata-providers`, () =>
    HttpResponse.json(metadataProviders),
  ),
  http.post(`${control}/v1/metadata-searches`, () =>
    HttpResponse.json(metadataResults),
  ),
  http.post(`${control}/v1/metadata-selections/:token`, ({ params }) =>
    String(params.token).includes("expired")
      ? HttpResponse.json(
          {
            error: {
              code: "selection_expired",
              request_id: "mock-selection-expired",
            },
          },
          { status: 410 },
        )
      : HttpResponse.json(mediaDetail, { status: 201 }),
  ),
  http.post(`${control}/v1/media-items/:itemId/release-searches`, () =>
    HttpResponse.json(releaseResults),
  ),
  http.get(`${control}/v1/download-destinations`, () =>
    HttpResponse.json(downloadDestinations),
  ),
  http.post(`${control}/v1/acquisitions`, () =>
    HttpResponse.json(acquisitions.submitted, { status: 201 }),
  ),
];
