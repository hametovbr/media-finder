## 1. Public environment contract

- [ ] 1.1 Add focused RED SDK tests for exact variable declarations, syntax, uniqueness, secret classification, missing-variable errors, and registry-wide conflicts.
- [ ] 1.2 Add the immutable public environment declaration and integration descriptor types and export them from the supported SDK boundary.
- [ ] 1.3 Update Manual, TMDB, and qBittorrent registrations and provider/client conformance fixtures to declare and validate their exact environment contracts.

## 2. Environment-only runtime composition

- [ ] 2.1 Add focused RED runtime tests proving TMDB, Prowlarr, and qBittorrent construct only from the specified process variables and ignore persisted integration settings.
- [ ] 2.2 Refactor runtime construction to resolve declared environment values into typed in-memory configuration while preserving secret redaction, official TMDB origin enforcement, cache ownership, and isolated HTTP clients.
- [ ] 2.3 Remove persisted `AppSetting` and client-payload reads from live integration resolution and return stable safe missing-variable and unavailable errors.

## 3. Single qBittorrent identity and migration

- [ ] 3.1 Add focused RED migration and acquisition tests for one deterministic system-owned qBittorrent row, archived legacy rows, cleared legacy payloads, preserved history, and new-submission rejection of legacy clients.
- [ ] 3.2 Add the schema/model migration and idempotent bootstrap for the system-owned qBittorrent identity without deleting historical Acquisition references.
- [ ] 3.3 Update release selection, submission, timeout lookup, and manual reconciliation to use only the environment-owned qBittorrent identity and live categories.

## 4. Read-only integration diagnostics

- [ ] 4.1 Add focused RED route/template/localization tests proving Settings exposes names and safe states but no values or integration mutation controls.
- [ ] 4.2 Remove provider, Prowlarr, client-create, archive, and restore settings handlers and replace the Settings view model with declaration and readiness diagnostics.
- [ ] 4.3 Update acquisition UI flows to remove client-instance selection while retaining explicit live destination selection and localized safe failure feedback.
- [ ] 4.4 Add Playwright coverage for missing, ready, and unavailable environment diagnostics, legacy-route rejection, Manual-only operation, and single-client acquisition selection in English and Russian.

## 5. Deployment and operator migration

- [ ] 5.1 Update Compose, environment examples, README, and operations guidance with the exact first-party variables, restart semantics, upgrade backup, and rollback requirements.
- [ ] 5.2 Extend documentation and delivery validators so examples cannot reintroduce persisted integration configuration, private values, or omitted required declarations.

## 6. Verification

- [ ] 6.1 Run focused SDK, module conformance, runtime, migration, acquisition, UI, security, and browser suites and record the RED-to-GREEN evidence.
- [ ] 6.2 Run frozen dependency installation, strict OpenSpec validation, documentation policy, formatting, lint, strict type checks, full unit/integration/contract/Playwright tests, asset rebuild with no diff, delivery validation, and production image checks available locally.
- [ ] 6.3 Perform a final diff review for secret disclosure, stale writable settings paths, legacy-client reachability, migration reversibility, and exact agreement between module manifests and deployment documentation.
