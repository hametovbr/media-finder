import { delay, http, HttpResponse } from "msw";

import {
  catalogItems,
  collections,
  downloadDestinations,
  manualErrors,
  manualMovieDetail,
  manualSeriesDetail,
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
    selected === "manual-confirmation" ||
    selected === "manual-csv-invalid" ||
    selected === "manual-expired" ||
    selected === "manual-invalid" ||
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
  http.get(`${control}/v1/media-items/:itemId`, ({ params }) => {
    const item =
      params.itemId === mediaDetail.id
        ? mediaDetail
        : params.itemId === manualMovieDetail.id
          ? manualMovieDetail
          : params.itemId === manualSeriesDetail.id
            ? manualSeriesDetail
            : null;
    return item === null
      ? HttpResponse.json(
          {
            error: {
              code: "media_item_not_found",
              request_id: "mock-request-2",
            },
          },
          { status: 404 },
        )
      : HttpResponse.json(item);
  }),
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
  http.post(`${control}/v1/manual-imports`, async ({ request }) => {
    const scenario = activeScenario(request);
    if (scenario === "manual-confirmation") {
      return HttpResponse.json(manualErrors.confirmation, { status: 409 });
    }
    if (scenario === "manual-invalid") {
      return HttpResponse.json(manualErrors.invalid, { status: 422 });
    }
    const body = (await request.json()) as {
      document?: { external_id?: string | null; kind?: "movie" | "series" };
    };
    if (body.document?.external_id === manualSeriesDetail.external_id) {
      return HttpResponse.json(manualErrors.confirmation, { status: 409 });
    }
    return HttpResponse.json(
      body.document?.kind === "series" ? manualSeriesDetail : manualMovieDetail,
      { status: 201 },
    );
  }),
  http.post(`${control}/v1/manual-imports/:token/confirm`, ({ params }) =>
    String(params.token).includes("expired")
      ? HttpResponse.json(manualErrors.expired, { status: 410 })
      : HttpResponse.json(manualSeriesDetail),
  ),
  http.put(`${control}/v1/media-items/:itemId/manual-metadata`, ({ params }) =>
    params.itemId === manualSeriesDetail.id
      ? HttpResponse.json(manualErrors.confirmation, { status: 409 })
      : HttpResponse.json(manualMovieDetail),
  ),
  http.post(
    `${control}/v1/media-items/:itemId/episode-imports`,
    async ({ request }) => {
      const body = (await request.json()) as { csv?: string };
      return activeScenario(request) === "manual-csv-invalid" ||
        body.csv?.includes("INVALID")
        ? HttpResponse.json(manualErrors.csvInvalid, { status: 422 })
        : HttpResponse.json(manualSeriesDetail);
    },
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
