# Task 7 report: Backend release hardening

## Scope

Remediated release-blocking backend findings across metadata retention, TMDB series coverage, integration security, bounded transports, public module contracts, and static module composition. The implementation preserves the MVP boundaries: one process, compile-time first-party modules, no runtime discovery, and provider-owned retention policy.

## Spec and architecture checks

- Clarified the active OpenSpec contracts for refreshed-revision purge behavior, isolated maintenance failures, complete TMDB season retrieval, bounded integration payloads, isolated HTTP sessions, and one public static registration boundary.
- Kept all TMDB calendar policy inside the TMDB module. Core maintenance only executes provider plans and persists provider-neutral outcomes.
- Exposed environment-reference, URL-validation, redaction, conformance-fixture, and module-registration contracts through the public SDK. First-party modules no longer import private core configuration.
- Centralized first-party module composition in an immutable registry used by runtime, maintenance, settings UI, attribution UI, and download-client configuration normalization.
- Retained static image-time module registration. No package discovery or runtime installation mechanism was added.

## TDD evidence

### Retention

The initial focused run reported two failures out of thirteen relevant tests: a successfully refreshed revision was excluded from later maintenance, and an unexpected provider exception aborted the run. The green run completed with 15 passing tests. A fake clock now advances beyond the provider-computed six-month expiry and proves that a refreshed TMDB revision is purged without repeated daily refreshes. Per-revision module, validation, and unexpected errors persist a safe standardized failure and do not prevent subsequent mandatory purge work.

### TMDB series and artwork

The initial focused run reported three expected failures because series fetch returned only the TV summary and normalized neither real season episodes nor artwork. The green run completed with 15 passing tests. Realistic fixtures cover TV details, Season 00, a regular season, episode runtime and ordering, poster/backdrop URLs, refresh, invalid identity, and strict endpoint rejection before bearer-token resolution.

### Transport isolation, redaction, and limits

The initial transport-hardening run failed all four new boundary tests. The green run passed all four. Separate clients now isolate TMDB, Prowlarr, and each qBittorrent instance; a same-host/different-port test proves that qBittorrent SID cookies cannot cross services. Prowlarr search JSON, result counts, and torrent artifacts are bounded with stable safe errors. Complete download URLs and passkeys are redacted at the HTTP logging boundary. The oversized-artifact case also proves one-use search-token semantics.

### UI form limits

The first integration check returned CSRF `403` instead of the required bounded-body `413`. The green check rejects both oversized `Content-Length` and oversized streamed bodies before decoding. The first whole-suite run then exposed three `Stream consumed` regressions in routes that intentionally decode the same request twice. Caching the already bounded decoded form on request state fixed the root cause without rereading the stream.

### Public registry and conformance

The initial registry/conformance run reported two failures while runtime still selected concrete modules directly and conformance was not capability-aware. Subsequent RED checks caught an incorrectly wired standardized client error fixture and a mutable registry mapping. The green implementation exercises declared provider/client capabilities, locale and identity preservation, retention, safe errors, and only supported artifact forms. A third-party test module passes without database, UI, or private imports. Registry mappings are immutable.

## Delivered behavior

- Refreshed TMDB revisions retain their original provider-computed expiry and are purged when due.
- TMDB TV fetch retrieves every advertised season detail, including Season 00, and normalizes upstream-shaped episodes and artwork.
- TMDB bearer requests are limited to typed, same-origin endpoint templates. Integration base URLs reject credentials, query, fragment, encoded unsafe components, and secret-bearing path segments while accepting safe reverse-proxy subpaths.
- HTTP cookie jars are isolated per integration and per qBittorrent instance.
- Prowlarr response bodies, search-result counts, torrent bytes, and UI form bodies have explicit limits and stable errors.
- The public SDK owns integration-facing environment references and static registration/conformance contracts.
- One immutable first-party registry is the runtime and UI composition boundary.

## Verification evidence

- Focused retention/TMDB tests: 15 passed.
- Focused transport tests: 4 passed.
- Focused release-route/form regression tests: 9 passed.
- Full Python suite: 224 passed with 90% total branch coverage.
- Ruff formatting and lint: passed.
- mypy: passed.
- strict OpenSpec validation: passed.
- frozen dependency installs, documentation policy, asset build/no-diff, delivery validator, and delivery mutation tests: passed.

## Self-review

- Confirmed that core maintenance contains no TMDB-specific duration or endpoint logic.
- Confirmed that Manual, TMDB, and qBittorrent modules do not import private core configuration or UI/database internals.
- Confirmed that no persisted or logged value contains magnet URLs, Prowlarr download URLs, passkeys, qBittorrent SID cookies, or bearer tokens.
- Confirmed that safe reverse-proxy subpaths remain accepted and that URL validation happens independently inside live transports.
- Confirmed that generated localization binaries were rebuilt from the English and Russian catalogs.

## Blockers

None.

## Backend re-review remediation

A release re-review identified four remaining boundary gaps. A new focused RED run failed all five probes: a normalized identity mismatch escaped maintenance and prevented a later mandatory purge; non-official TMDB origins were accepted; repeated Prowlarr and module-construction failures retained six open HTTP clients; Manual could not complete a successful fixture fetch; and a provider could omit essential capability declarations while passing conformance.

The GREEN implementation adds a savepoint around the complete plan/apply/persist lifecycle of each revision. Domain revision persistence can now participate in the caller-owned transaction without committing it. Any plan shape, media-kind conversion, provider operation, identity check, normalized-model validation, or domain persistence exception rolls back only that savepoint; a separate savepoint records the safe failure before later subjects proceed.

TMDB configuration and its live transport now canonicalize only `https://api.themoviedb.org/3`; plaintext, alternate hosts, alternate paths, explicit ports, credentials, queries, and fragments are rejected before bearer resolution. Prowlarr validation and metadata/download module builders track the HTTP-client-list checkpoint for each attempt, immediately close clients created by a failed attempt, and remove them from runtime ownership.

Metadata-provider conformance now requires manifests to advertise `search`, `fetch`, and `normalize` and executes successful search and fetch unconditionally before normalization, identity, locale, error, attribution, and retention checks. Manual supports deterministic in-memory fixture identities for this contract without database or UI access, and TMDB advertises the same essential operations.

Final remediation verification:

- Focused RED: 5 failed out of 5.
- Focused GREEN: 5 passed; expanded backend regression: 40 passed.
- Full Python suite: 226 passed with 90% total branch coverage.
- Ruff format/check and mypy: passed.
- Strict OpenSpec and documentation-language policy: passed.
- Asset build/no-diff, seven delivery mutation tests, and delivery validation: passed.
- Blockers: none.

## Final runtime-ownership and conformance remediation

A final review found that `RuntimeResolver` validated a TMDB provider or qBittorrent client only after `DefaultRuntimeFactory` had cached the integration and retained its HTTP client. It also found that provider conformance allowed an error fixture to omit its expected standardized code.

The focused RED run failed both probes: an unavailable TMDB endpoint was returned as a successful cached provider, and `ProviderConformanceFixture.expected_error_code` still defaulted to `None`. The GREEN implementation performs live provider/client validation inside the factory before cache insertion. Failed validation reuses the existing attempt checkpoint to close and forget only clients created by that attempt. Successful integrations are cached and reused without repeated authentication; a later failed integration does not cross-close them. Resolver delegates to that ownership boundary and no longer validates after caching.

`expected_error_code` is now a mandatory fixture field and every provider conformance run unconditionally performs an invalid-identity fetch and asserts its public `ModuleError` code. The Manual fixture demonstrates `manual_import_invalid`; TMDB and the independent fixture provider retain their coherent codes.

Final verification after this remediation:

- Focused RED: 2 failed out of 2; focused GREEN: 3 passed.
- Expanded backend regression: 44 passed.
- Full Python suite: 228 passed with 90% total branch coverage.
- Ruff format/check, mypy, strict OpenSpec, documentation policy, asset no-diff, seven delivery mutation tests, and delivery validation: passed.
- Blockers: none.

## Final integration-boundary remediation

A holistic review found five remaining integration gaps. The focused RED run failed all five probes: authenticated Prowlarr torrent resolution accepted same-origin URLs outside its configured reverse-proxy path; a non-canonical but valid Manual UUID could bypass existing-item confirmation; manual reconciliation required an unrelated live Prowlarr integration; Manual was constructed directly by UI routes instead of the public registry; and numeric HTTP-client checkpoints allowed a failing concurrent attempt to close a later successful integration.

The GREEN implementation constrains Prowlarr downloads to the configured normalized path before resolving or sending the API key. It rejects unrelated prefixes, prefix confusion, dot traversal, encoded path confusion, and backslashes while retaining valid in-prefix downloads and disabled redirects. Manual JSON identities now pass through provider validation and UUID canonicalization before database lookup, so an existing identity always requires explicit confirmation and creates a new immutable revision only after confirmation.

Manual reconciliation now depends only on the pinned Acquisition, its active download-client instance, and the exact correlation token. The built-in Manual provider is a first-class registration with an empty typed configuration, generic runtime construction and discovery, attribution, and no-op retention. Manual routes resolve it through runtime composition and contain no concrete provider constructor.

Runtime client ownership is per construction attempt. Cache inspection and adoption are synchronized, network validation remains outside the lock, and a losing or failed attempt closes only its own clients. A deterministic interleaving test proves that a failing TMDB attempt cannot close or remove a later successful cached qBittorrent client; successful integrations remain cached and reused.

Final verification for this remediation:

- Focused RED: 5 failed out of 5; focused GREEN: 5 passed.
- Expanded backend regression: 55 passed.
- Full Python suite: 239 passed with 90% total branch coverage.
- Ruff format/check and strict mypy: passed.
- Strict OpenSpec validation and documentation-language policy: passed.
- Asset build/no-diff, seven delivery mutation tests, and delivery validation: passed.
- The synchronized root `openspec/specs/` tree remained untracked and untouched.
- Blockers: none.
