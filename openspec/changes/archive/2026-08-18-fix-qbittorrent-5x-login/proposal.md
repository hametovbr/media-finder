## Why

qBittorrent 5.x returns `HTTP 204 No Content` with an empty body (plus a session `Set-Cookie`) on a successful `POST /api/v2/auth/login`, while older releases returned `200` with the body `Ok.`. The download-client module's `QbittorrentTransport.authenticate()` treats anything other than `Ok.` as a failure, so a correctly configured qBittorrent 5.x instance is reported as `download_client_authentication_failed` and torrent acquisition is unavailable.

## What Changes

- Accept both `200 Ok.` and an empty successful login response (e.g. `204 No Content`) in `QbittorrentTransport.authenticate()`.
- Extend the isolated qBittorrent module tests to cover the qBittorrent 5.x login response shape.
- No change to the module manifest, environment contract, destinations, submission, correlation, conformance fixtures, or serialized artifacts.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This is a compatibility bug fix: it restores the already-specified qBittorrent submission contract without changing any spec-level behavior.

## Impact

- `packages/modules/download-qbittorrent/src/media_finder_download_qbittorrent/transport.py`: widen the login success check.
- `packages/modules/download-qbittorrent/tests/test_qbittorrent_module.py`: add a deterministic fake for the 204 login response and an assertion that authentication succeeds.
- No manifest, schema, conformance fixture, Compose, documentation, or dependency changes.
