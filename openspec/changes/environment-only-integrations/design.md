## Context

See `proposal.md` for motivation. Runtime construction currently combines persisted `AppSetting` payloads, persisted `DownloadClientInstance.config_payload`, and environment references. Generic Settings forms write those payloads, so container configuration alone does not describe the effective deployment. The module registry already owns static construction and is the narrowest place to declare module requirements.

## Goals / Non-Goals

**Goals:**

- Make the process environment the single writer and source of truth for all first-party external integrations.
- Make exact environment names discoverable and conformance-tested through the public module SDK.
- Preserve acquisition history across the breaking removal of user-managed client instances.
- Keep diagnostic visibility without exposing resolved values.

**Non-Goals:**

- Multiple qBittorrent instances or dynamic environment prefixes.
- Runtime-installed modules, environment-file editing, secret management, or container restart controls in Media Finder.
- A compatibility mode that continues reading persisted integration settings.
- Changes to provider retention ownership, torrent handoff semantics, or post-submission tracking.

## Decisions

### Use immutable exact environment declarations in public registrations

Add a public immutable environment declaration type containing `name`, `required`, `secret`, and `description_key`. Metadata-provider and download-client registrations expose ordered tuples of declarations. Prowlarr uses the same declaration type through a core integration descriptor because it is an adapter rather than a module.

Exact names are constants owned by their implementations:

| Integration | Variables |
| --- | --- |
| TMDB | `TMDB_TOKEN` |
| Prowlarr | `PROWLARR_URL`, `PROWLARR_API_KEY` |
| qBittorrent | `QBITTORRENT_URL`, `QBITTORRENT_USERNAME`, `QBITTORRENT_PASSWORD` |

The declaration exposes names and classifications, never values. Shared validation enforces portable uppercase names matching `[A-Z][A-Z0-9_]*`, uniqueness, non-empty description keys, and consistent secret classification. Conformance requires missing-variable behavior and verifies that diagnostics contain no resolved secret.

Alternative rejected: one JSON environment variable. It weakens discoverability, secret classification, Compose ergonomics, and module conformance. Dynamic prefixes for multiple instances are also rejected because there is no current multiple-client requirement and they cannot publish a finite exact list.

### Build validated typed configuration from environment at the composition boundary

Modules retain typed Pydantic configuration models as an internal validation boundary, but core constructs their input mapping from declared environment variables. The mapping exists only in memory. `RuntimeResolver` no longer queries `AppSetting`; module builders no longer accept operator-selected `env:NAME` references. Secret resolution happens once at construction and remains subject to existing redaction and per-attempt HTTP-client ownership.

Registration conformance compares independent expected declarations, exercises every required-variable omission, validates secret classification, and constructs the production module builder before the fixture-backed behavior suite runs. Runtime shutdown marks the factory closed under the same lock used for cache publication, so an in-flight build cannot repopulate caches or retain a client after shutdown.

TMDB keeps its official HTTPS origin as a module constant. Making the origin an environment option would reopen the credential-forwarding risk already removed by the fixed-origin validation.

Alternative rejected: retaining database payloads as fallback. Two sources of truth would preserve the original ambiguity and make rollback dependent on database state.

### Represent the sole qBittorrent client with a deterministic system row

Acquisition persistence still needs a stable client foreign key. A migration introduces or identifies one system-owned qBittorrent row with a deterministic UUID, fixed display name `qBittorrent`, module key `qbittorrent`, empty configuration payload, and an explicit system-owned marker. Startup idempotently verifies that row. New acquisition discovery, submission, and reconciliation resolve only this row through environment configuration.

Existing client rows are retained because Acquisitions reference them. The migration archives non-system rows, removes their stored configuration payloads, and deletes legacy provider/Prowlarr `AppSetting` rows so credentials or references are not retained in active storage. It chooses collision-free legacy display names and is idempotent across an interrupted SQLite column-add operation. Historical records remain displayable, but legacy rows cannot be restored, selected, or resolved for new client calls.

Alternative rejected: removing the foreign key or hard-deleting client rows. Either requires a broader acquisition-schema redesign or destroys history.

### Replace writable Settings with safe diagnostics

Remove provider, Prowlarr, client-create, archive, and restore handlers and forms. Settings derives a view from static declarations plus the current process environment:

- `set` means a variable is present and non-empty;
- `missing` means a required variable is absent or empty;
- `ready` means construction and the existing live validation succeed;
- `unavailable` means declarations are satisfied but live validation fails.

Only exact names, required/secret flags, translated descriptions, and states are rendered. Values, lengths, hashes, partial masks, and upstream error bodies are never exposed because even masked values create avoidable disclosure and comparison signals.

### Apply environment changes only at process construction

Successful integrations may remain cached for the process lifetime. Operators apply changes by recreating or restarting the container. This avoids polling environment state and produces an explicit, observable lifecycle consistent with Compose and Komodo deployments.

Alternative rejected: reading `os.environ` on every request. It adds no value in a container, complicates cache ownership, and still cannot observe a Docker environment change without process recreation.

## Risks / Trade-offs

- **[Breaking removal of multiple clients]** Existing multi-client deployments lose new-submission access to those instances. → Preserve history, archive legacy rows, document the single-instance limitation, and require no destructive deletion.
- **[Environment names can collide across third-party modules]** Two installed modules could claim the same variable with incompatible classifications. → Validate registry-wide uniqueness or identical compatible declarations at static composition and fail startup on conflict.
- **[Live readiness can be slow or unavailable]** Settings status may depend on external requests. → Preserve bounded transport timeouts and report `unavailable` independently from `/health/ready`.
- **[Legacy secrets or references remain in backups]** Migration can clear active rows but cannot rewrite prior backups. → Document the migration and advise rotating credentials if literal secrets were ever stored contrary to policy.
- **[Rollback to an older image expects persisted settings]** Cleared legacy payloads cannot restore the former configuration model. → Rollback requires restoring the pre-upgrade `/data` backup, which is already mandatory before upgrades.

## Migration Plan

1. Back up `/data` before deploying the new image.
2. Deploy all required environment variables with the new image.
3. Run the migration that creates the deterministic system qBittorrent row, archives legacy client rows, and clears legacy integration payloads.
4. Start the application and verify local database readiness independently from integration diagnostics.
5. Verify Settings reports declared variables and expected integration states without values.
6. Roll forward by correcting environment variables and recreating the container. Roll back only by restoring both the prior image and the pre-upgrade `/data` backup.
