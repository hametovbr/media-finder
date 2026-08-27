## 1. Typed Control Boundary and Deterministic Fixtures

- [x] 1.1 Add focused failing control-client tests for Manual import, confirmation, edit, and episode-CSV requests, including CSRF/JSON headers, encoded path parameters, and generated request/response shapes; run them and record the expected RED result.
- [x] 1.2 Add failing security tests proving that only a well-formed `confirmation_required` error with `kind: "manual"` exposes an opaque confirmation token and that unrelated, malformed, or arbitrary error details are discarded; run them and record RED.
- [x] 1.3 Implement the four narrow typed Manual client methods and allowlisted confirmation-detail extraction using the existing request/error infrastructure, then run the focused client tests to GREEN.
- [x] 1.4 Extend MSW fixtures and handlers with Manual movie, rich Manual series including Season 00, duplicate confirmation, invalid document, expired confirmation, successful CSV, and atomic CSV failure states without reimplementing backend normalization.

## 2. Complete Manual Document Editor

- [x] 2.1 Add failing pure tests for structured-create defaults and `MediaItemDetail`-to-`ManualDocumentV1` mapping, covering the session metadata locale, generated identity omission on create, immutable identity and kind on edit, rich unexposed field preservation, other-locale title preservation, and Season 00 hierarchy; run them and record RED.
- [x] 2.2 Implement typed pure document/default/mapping helpers that keep one complete Manual document, use presentation-only stable row keys where needed, and strip only those keys before submission; run the mapping tests to GREEN.
- [x] 2.3 Add failing component tests for the common structured movie/series fields, season and episode groups, explicit row addition/removal, locked edit identity, collection context, keyboard operation, first-invalid-field feedback, and responsive no-overflow structure; run them and record RED.
- [x] 2.4 Implement the shared structured editor with existing Mantine, React, and i18next primitives and no new runtime dependency, then run its focused unit and accessibility tests to GREEN.

## 3. Manual Create, JSON Import, and Confirmation

- [x] 3.1 Add failing router and add-page tests for explicit provider-versus-Manual choice, the `/add/manual` bookmark, localized not-found behavior for `/about`, and absence of a provider search when Manual is chosen; run them and record RED.
- [x] 3.2 Register the Manual-add route and add the explicit Manual choice while leaving provider search behavior and all omitted secondary routes unchanged; run the focused route tests to GREEN.
- [x] 3.3 Add failing page tests for structured movie creation, structured series creation with regular seasons and Season 00, optional collection context, navigation to the saved detail, and no Acquisition or automatic release search; run them and record RED.
- [x] 3.4 Implement structured Manual create through the existing import operation and invalidate the relevant TanStack Query state before detail navigation; run the focused create tests to GREEN.
- [x] 3.5 Add failing tests for pasted and locally loaded complete schema-v1 JSON, syntax/non-object/schema-version feedback, preservation of supplied valid identity and rich fields, server-owned semantic validation, and safe invariant errors; run them and record RED.
- [x] 3.6 Implement in-memory JSON paste/file loading and bounded client shape checks, submit the complete generated-contract document without field rewriting, and run the focused JSON tests to GREEN.
- [x] 3.7 Add failing tests for explicit duplicate-identity confirmation, cancellation, successful one-time confirmation, expired/consumed-token recovery, retained source input, no automatic replay, and absence of the token from URLs, durable storage, snapshots, logs, and rendered errors; run them and record RED.
- [x] 3.8 Implement the ephemeral Manual confirmation dialog and fresh-originating-request recovery path, then run the focused confirmation and security tests to GREEN.

## 4. Lossless Manual Edit and Atomic Episode CSV

- [x] 4.1 Add failing media-detail and edit-route tests proving that only `provider_key: "manual"` exposes an edit action, a direct non-Manual edit bookmark is non-actionable, and neither case invokes a legacy form or processor route; run them and record RED.
- [x] 4.2 Register `/items/:itemId/edit`, add the conditional detail action, fetch item/session state through the control client, and implement localized non-Manual rejection; run the focused gating tests to GREEN.
- [x] 4.3 Add failing edit tests that change one visible field in a rich imported movie and series, preserve all untouched normalized fields and non-active-locale titles, lock `external_id` and kind, retain untouched rows, deliberately remove selected season/episode rows, and handle edit confirmation; run them and record RED.
- [x] 4.4 Implement lossless complete-document edit submission, deliberate hierarchy removal, query invalidation, and detail navigation without creating an Acquisition; run the rich edit tests to GREEN.
- [x] 4.5 Add failing tests for Manual-series-only CSV paste/file loading, empty and over-one-mebibyte client feedback, one raw control request for valid CSV, resulting revision display, invalid-row safe feedback, and no partial UI state; run them and record RED.
- [x] 4.6 Implement raw in-memory CSV submission through the existing atomic episode-import operation without browser-side CSV parsing or row mutations, then run the focused CSV tests to GREEN.

## 5. Localization, Browser, and Host Boundaries

- [x] 5.1 Add every new visible label, instruction, confirmation, validation, success, and invariant-error message to both English and Russian catalogs, and extend locale parity tests before resolving any missing-key failures.
- [x] 5.2 Add failing accessibility coverage for the Manual routes, nested series controls, removal actions, validation alerts, confirmation dialog, and keyboard flow in both locales; remediate with existing presentation primitives and run `pnpm ui:a11y` to GREEN.
- [x] 5.3 Add failing Playwright scenarios for bookmarked Manual-add/edit routes, structured movie creation, rich series edit with Season 00, JSON duplicate confirmation and expiry recovery, CSV success/failure, control-only browser traffic, desktop, mobile, English, and Russian states; run them and record RED.
- [x] 5.4 Complete deterministic MSW state transitions and responsive presentation needed by those scenarios, then run `pnpm ui:browser` to GREEN and verify that no request targets `/api/v1` or a removed HTML mutation route.
- [x] 5.5 Add failing static-host and composed-server regression cases for the two SPA bookmarks, legacy form rejection without state change, unchanged `/api/control/v1/about` availability, and packaged localized assets; run them and record RED.
- [x] 5.6 Rebuild deterministic bundled assets through the supported frontend build, make only the minimal host/asset adjustments exposed by the tests, and run static-host, composition-root, browser-security, and control-parity tests to GREEN.

## 6. Repository Guidance and Contract Closure

- [x] 6.1 Update `openspec/config.yaml` to describe the React/Vite built-in interface and retain the existing one-process, SQLite, module, and secret constraints.
- [x] 6.2 Update current English contributor, browser-control, implementation-plan, operations, and clean-checkout guidance to include the supported Manual routes and workflows, remove stale Jinja2/HTMX, Settings, About/Credits, omitted-Manual, and obsolete command claims, and leave archived change history untouched.
- [x] 6.3 Run documentation-language and targeted source checks proving that current guidance no longer promises removed presentation paths and that no built-in About/Credits route, new control endpoint, schema change, environment variable, dependency, process, service, or migration was introduced.
- [x] 6.4 Run control OpenAPI generation in check mode and inspect the diff; if the checked contract or generated types change, stop apply and use `openspec-update-change` because this proposal authorizes no public contract change.

## 7. Exact-Candidate Verification and OpenSpec Handoff

- [x] 7.1 Run focused Manual frontend tests plus the existing backend Manual gateway, API, real-conformance, contract, and OpenAPI suites; resolve regressions without duplicating backend rules in the browser.
- [x] 7.2 Run frontend format, lint, typecheck, unit, accessibility, browser, contract-drift, and production-build commands, preserving the originating exit status for any filtered output.
- [x] 7.3 Run repository Python format, lint, type, full test, architecture-boundary, delivery, module-conformance, deterministic-asset drift, isolated-wheel/package, composed-server, and production-image smoke gates documented for the exact candidate; report unavailable environment-sensitive gates as blocked or not run rather than passed.
- [x] 7.4 Run `pnpm spec:validate`, `openspec validate --all --strict`, `openspec list --json`, documentation checks, and `git diff --check`; inspect the complete diff and worktree for unrelated files and secrets.
- [x] 7.5 Present apply results and stop without synchronizing canonical specs or archiving; obtain a separate user request for the required OpenSpec sync/archive and subsequent delivery phases.
