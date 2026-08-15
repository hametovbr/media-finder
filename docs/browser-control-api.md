# Browser control API

The versioned browser contract at `/api/control/v1` is the supported boundary
for independently developed Media Finder interfaces. The bundled Jinja and
HTMX interface uses the same typed gateway as this JSON adapter; it has no
direct persistence or integration access.

The deterministic OpenAPI document is stored at
[`docs/api/control-v1.openapi.json`](api/control-v1.openapi.json). Consumers
should generate clients or validate requests against that checked-in snapshot.
Additive response fields may appear within v1. Removing or changing an existing
field, operation, status, or semantic invariant requires a new API version.

## Browser session and security

Start a browser session with:

```http
GET /api/control/v1/session
```

The response sets the `mf_session` cookie and returns a CSRF token, the UI and
metadata locales, and the supported locales. The cookie is `HttpOnly` and
`SameSite=Lax`; production HTTPS deployments must set
`MEDIA_FINDER_SECURE_COOKIE=true`.

Every mutating request must:

- use `Content-Type: application/json`;
- send the current token in `X-CSRF-Token`;
- send an `Origin` matching the externally visible origin;
- remain below the one-megabyte body limit.

CORS is intentionally disabled. The processor Bearer token for `/api/v1` must
never be placed in browser code. Both the external UI and `/api/control` need
the same reverse-proxy authentication policy when published on a network.

Errors use a stable machine `code`, a request ID, and safe details. Provider
payloads, download URLs, torrent bytes, credentials, and integration variable
values are never returned. Metadata, Manual, and release choices use bounded
opaque tokens; clients must treat them as short-lived and may need to repeat a
search after expiry or eviction.

## Independent built-in UI development

The built-in UI wheel contains its templates, static files, gettext catalogs,
and presentation code. It depends only on `media-finder-control-contracts` and
web libraries. Run it against deterministic fixtures without a database or
external service:

```console
uv run media-finder-ui-dev
```

The development host is for local UI work only. Backend behavior must be tested
against the real `ControlGateway` implementation and the HTTP adapter
conformance suite.

## Same-origin external UI topology

An alternative frontend remains a separate deployment concern. Route it and
Media Finder beneath one externally authenticated HTTPS origin:

```text
https://media.example.test/             -> external frontend
https://media.example.test/api/control/ -> Media Finder
https://media.example.test/api/v1/      -> Media Finder
https://media.example.test/health/      -> Media Finder
```

With Traefik, create routers with those path prefixes, apply the same external
authentication middleware to the frontend and `/api/control`, and preserve the
original scheme and host. Do not strip `/api/control`; Media Finder mounts the
versioned API beneath it. `/api/v1` keeps its independent Bearer requirement.
No cross-origin mode or browser token is supported.

Set `MEDIA_FINDER_UI_MODE=disabled` only after the external frontend is ready.
This removes bundled HTML and static routes while retaining both APIs, health,
migrations, maintenance, and storage in the same Media Finder container. To
roll back the frontend, restore `MEDIA_FINDER_UI_MODE=builtin` and recreate the
container. This change adds no persistent data and requires no database
migration.
