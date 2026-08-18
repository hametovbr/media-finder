## 1. Authentication compatibility

- [x] 1.1 Add a focused failing isolated-module test that authenticates successfully when `/api/v2/auth/login` returns `204` with an empty body and a session cookie; observe RED.
- [x] 1.2 Widen `QbittorrentTransport.authenticate()` to accept an empty successful login body alongside `Ok.`; make the focused test GREEN.

## 2. Verification

- [x] 2.1 Run the qBittorrent module tests, `pnpm module-conformance:test`, `pnpm module-conformance:validate`, `pnpm spec:validate`, and the Python format, lint, and type gates; confirm no regressions.
