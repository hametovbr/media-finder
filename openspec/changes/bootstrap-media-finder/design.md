## Context

The repository starts without application code. The approved capabilities span persistent catalog state, two kinds of extension module, external HTTP integrations, processor-facing exports, a bilingual web UI, and container delivery. See `proposal.md` for motivation and the six capability specs for observable behavior.

The target is a small self-hosted deployment with one operator and external reverse-proxy authentication. Media files are deliberately outside the application boundary. Provider terms require TMDB-derived data to have provider-controlled refresh and expiry, while Manual data must remain durable.

## Goals / Non-Goals

**Goals:**

- Keep one deployable process and one local database while maintaining strict logical module boundaries.
- Make provider and client integrations independently implementable and contract-testable.
- Preserve immutable metadata and acquisition history while allowing provider-owned payload cleanup.
- Prevent release credentials and torrent artifacts from entering persistence or logs.
- Give external processors deterministic, versioned metadata, naming, and NFO contracts.
- Keep implementation and future architectural changes governed by OpenSpec.

**Non-Goals:**

- Establishing a general runtime plugin marketplace or untrusted-code sandbox.
- Owning media files, post-processing, download state, or library scanning.
- Solving multi-user authorization, horizontal scaling, durable background jobs, or high availability.
- Automatically resolving identity across metadata providers.
- Creating a generic naming-profile plugin framework in the MVP.

## Decisions

### 1. Use one Python application with internal package boundaries

Use CPython 3.13, `uv` with a committed `uv.lock`, FastAPI, Jinja2, HTMX, locally built web assets, SQLAlchemy 2, Alembic, Babel/gettext, and one Uvicorn worker. Store state in SQLite WAL under `/data`.

Modules are Python packages inside the repository and image, not separately deployed services. This preserves independent contracts without adding network failure modes, version negotiation, or operator burden. A service split becomes justified only by measured independent scaling, a security boundary, or independent ownership.

Alternatives rejected:

- A SPA duplicates validation and localization models and requires a separate build/runtime contract without an MVP requirement.
- Redis, a task queue, and a separate worker add state and recovery duties for daily best-effort maintenance and user-driven submissions.
- Runtime package installation makes supply-chain, compatibility, and migration safety substantially harder.

### 2. Keep domain state explicit and immutable where history matters

Use relational records for Collection, MediaItem, MetadataRevision, Acquisition, DownloadClientInstance, and AppSetting. MediaItem identity is provider-scoped. MetadataRevision stores an envelope plus raw, normalized, overrides, and effective JSON payloads, with a normalized `schema_version` and provenance. Acquisition pins a revision and the `jellyfin-v1` profile.

Archive timestamps replace hard deletion. Database constraints enforce one provider/external identity and one Acquisition per idempotency key. A normalized title/year similarity query informs users but never establishes identity.

Alternatives rejected:

- Mutable metadata rows lose the exact snapshot used by a download.
- A document database adds another operational dependency while the domain has strong relational identity and lifecycle constraints.
- Cross-provider auto-matching introduces ambiguity without a reliable product requirement.

### 3. Publish narrow typed module contracts

Define versioned Pydantic public types and protocols in a core SDK package. A metadata provider exposes its manifest, capabilities, config validation, search, fetch, normalization, attribution, standardized errors, and retention planning/execution hooks. A download client exposes its manifest, config validation, live destinations, artifact submission, and exact-correlation lookup.

Core owns orchestration and persistence through service interfaces. Modules receive data and narrowly scoped HTTP/runtime services, never database sessions or template directories. Manifests reference typed config fields and translation keys; core renders generic forms. Shared conformance suites run against fixture-backed module factories.

Alternatives rejected:

- Inheritance from application services leaks internals and makes third-party implementation fragile.
- Arbitrary module HTML/JavaScript defeats the generic security and localization model.
- Over-generalizing Prowlarr as a public module contract is deferred until a second release-search backend exists.
- AniList is not an MVP provider because its API terms prohibit using the service as a data-storage or backup mechanism, which conflicts with immutable provider snapshots.

### 4. Put retention decisions entirely in metadata providers

The revision envelope carries optional provider-supplied maintenance timestamps and status. Core runs a provider-agnostic maintenance coordinator at startup and once per day. It enumerates every installed registered provider type owning persisted revisions, including providers without current active configuration, passes due revision references through their public hook, and applies generic returned actions transactionally.

The TMDB package alone computes five-calendar-month refresh and six-calendar-month expiry using calendar arithmetic and defines refresh plus mandatory-at-expiry purge actions. The Manual package returns no due work. Core code and configuration contain no TMDB name, duration, or special-case branch. Export authorization checks module-computed expiry synchronously so delayed maintenance never serves expired derived data.

Purge clears provider-derived raw, normalized, and effective payload columns but retains revision identity, timestamps, locale, provenance descriptor, user overrides, MediaItem, and Acquisition relationships. Export services map a missing expired pinned payload to 410.

Alternatives rejected:

- A global TTL setting violates provider ownership and cannot represent different terms.
- Deleting the revision breaks historical referential integrity.
- A separate scheduler container is not justified for once-daily in-process work.

### 5. Treat torrent discovery as an ephemeral capability

Use a Prowlarr adapter for torrent-only interactive search. Cache normalized search results and their sensitive resolution data in a bounded process-memory TTL cache. Send the browser a random opaque token mapped to a cache entry. Restart or expiry intentionally invalidates outstanding selections.

On selection, reload client destinations, validate the requested destination, create a pending Acquisition transactionally, resolve the magnet or torrent bytes in memory, and call the client. Persist only a sanitized release snapshot. URL sanitization removes userinfo, query, and fragment before storage or logging.

Alternatives rejected:

- Persisting results or torrent artifacts creates passkey and credential exposure with little value for a manual workflow.
- Rehydrating expired search results from URLs makes stale or tampered submission more likely.
- Usenet support would require a different artifact and client contract and is outside the MVP.

### 6. Use idempotency plus exact correlation at the submission boundary

Generate the Acquisition UUID before client submission and derive `mf-acq-<uuid>` exactly. A unique caller idempotency key returns the existing Acquisition. The qBittorrent implementation maps destination to category and correlation to tag.

Definitive acceptance produces `submitted`; definitive rejection produces `failed`. On timeout, immediately perform exact-correlation lookup. Found means `submitted`; a conclusive absence means `failed`; an inconclusive lookup remains `pending` for explicit manual reconcile. Startup never auto-resubmits pending rows.

This deliberately stops after submission. Download progress belongs to the client and file processing belongs to an external processor.

Alternatives rejected:

- Automatic retry after an ambiguous timeout can duplicate downloads.
- Polling client progress expands states and failure semantics without serving the catalog/export goal.

### 7. Version processor contracts independently of file formats

Protect all `/api/v1/*` routes with one constant-time-checked Bearer token resolved from the environment. Expose current and pinned effective metadata; never raw provider payloads. Use a request-ID middleware and one safe error envelope.

Implement `jellyfin-v1` as a fixed naming service, not a module. Inputs identify a movie, series, season, episode, or ordered episode range and optionally provide a validated extension. Outputs include relative directory, basename, optional extension, full relative path, and NFO filename. Sanitization operates per component, preserves Unicode, rejects traversal, removes control/reserved characters, and protects platform-reserved names. The extension is data, never a built-in container assumption.

Render NFO with a structured XML builder for movie, tvshow, season, and one episode. A multi-episode NFO request returns 422 because one portable episode NFO cannot faithfully represent multiple Jellyfin episodes, while naming remains supported.

Alternatives rejected:

- Filename templates in the MVP add a user-facing language and migration burden before a second profile exists.
- String-concatenated XML is too easy to emit invalid or unsafe output.
- A provenance sidecar duplicates NFO storage responsibility; warning headers communicate provider expiry without another file contract.

### 8. Use server-rendered UI with independent locale choices

Jinja2 owns full-page rendering and HTMX owns bounded fragment replacement. English is the source locale. Babel/gettext catalogs provide English and Russian strings. UI locale resolution order is an explicit cookie, supported browser preference, then English. Metadata locale is stored independently per request/session and initially inherits UI locale.

The add flow persists a confirmed item before offering release search. Provider results remain separated by source. Session data is cryptographically signed; every mutation requires a session-bound CSRF token. Cookie flags are HttpOnly and SameSite=Lax, with Secure controlled by an HTTPS deployment setting.

The low-fidelity artifact at `docs/design/wireframe.html` defines the intended navigation and flow, not production assets.

Alternatives rejected:

- A local account database duplicates reverse-proxy identity and authorization without a multi-user requirement.
- Automatic provider-result merging hides ambiguous identity decisions.

### 9. Gate startup, delivery, and releases with reproducible checks

An entrypoint runs Alembic before starting one Uvicorn worker. Liveness checks only process service; readiness checks database access and migration head. External integration health appears in settings/checklist and cannot fail readiness.

The production image runs non-root and stores mutable state only in `/data`. `compose.example.yaml` binds HTTP to localhost, uses a named data volume, and contains no media/download mount. GitHub Actions runs documentation, OpenSpec, Python, contract, browser, and image checks. A separate release workflow builds amd64/arm64 images and applies the documented tags.

Alternatives rejected:

- Auto-starting with an old schema risks silent corruption.
- Coupling readiness to providers makes an external outage restart a healthy catalog.
- User-specific proxy labels or network names make the example unsafe to copy.

## Risks / Trade-offs

- **[Single-process maintenance can be delayed by downtime]** → Run on startup, then daily; record outcomes and make maintenance observable.
- **[In-memory search tokens vanish on restart]** → Treat this as safe invalidation and require a fresh manual search.
- **[SQLite limits horizontal writes]** → Run one worker and document the boundary; consider another database only after measured contention or an HA requirement.
- **[Static modules require a release to install]** → Keep contracts small and conformance tests public; revisit signed runtime modules only after real external demand.
- **[Provider purge reduces historical exportability]** → Retain envelopes, identities, overrides, and acquisitions; return an explicit 410 instead of stale or fabricated data.
- **[External proxy authentication can be omitted by operators]** → Bind the example to localhost and document authentication as mandatory before network exposure.
- **[Cross-platform filename rules can over-sanitize]** → Preserve Unicode, use deterministic component-level snapshots, and cover Windows/POSIX/Jellyfin edge cases.

## Migration Plan

1. Bootstrap OpenSpec, repository policies, contribution skills, and design artifacts without application code.
2. Implement schema and migrations, then provider/client contracts and metadata providers.
3. Add acquisition submission and recovery against deterministic fakes.
4. Add protected exports and naming/NFO snapshots.
5. Add the localized UI and browser tests.
6. Add the production image, Compose example, CI, and release workflow.
7. Validate the full change, synchronize specs, archive the change, and publish the first stable release.

Before every later upgrade, back up `/data`. If migration or startup validation fails, stop the new container, restore the backup, and redeploy the previous immutable image tag.
