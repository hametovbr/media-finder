## Context

`QbittorrentTransport.authenticate()` posts `username`/`password` to `/api/v2/auth/login` through a single isolated `httpx.Client`, then requires the response text to equal `Ok.`. `_post_text` already calls `response.raise_for_status()`, so any non-2xx response raises before the text is read. qBittorrent 5.x returns `204 No Content` (empty body, session cookie set) on successful login. See `proposal.md` for the observed behavior.

## Goals / Non-Goals

**Goals:**

- Make the qBittorrent module authenticate successfully against both the legacy `200 Ok.` and the qBittorrent 5.x `204 No Content` login responses.

**Non-Goals:**

- No change to destinations, submission, correlation, manifest, environment declarations, or conformance fixtures.

## Decisions

### Decision 1: Treat an empty successful login body as success

Change `authenticate()` to raise only when the trimmed response text is neither `Ok.` nor empty, mirroring the existing `_require_accepted` helper's accepted set of `{"", "Ok."}`.

- **Why**: `raise_for_status()` already rejects non-2xx responses, so after it succeeds an empty body unambiguously means a successful `204`. Accepting `""` keeps legacy `Ok.` handling intact while adding qBittorrent 5.x compatibility.
- **Alternatives considered**: checking the HTTP status code directly (would require threading the status through `_post_text`, changing its return type); special-casing `204` only (more code for the same result); adding a version probe (unnecessary network round-trip).

## Risks / Trade-offs

- [An empty body on a future non-success 2xx login would be treated as success] → mitigated because `raise_for_status()` fails on non-2xx and qBittorrent uses `401`/`403` for rejected credentials; the cookie-based session is still exercised by every subsequent authenticated call.

## Migration Plan

No migration. Existing qBittorrent 4.x deployments keep working; qBittorrent 5.x deployments begin authenticating without any configuration change.

## Open Questions

None.
