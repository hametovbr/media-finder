## Context

See `proposal.md` for the motivation and `specs/bilingual-web-ui/spec.md` for the reconciled behavior. The built-in UI is now a React SPA packaged as deterministic static assets behind a minimal Python ASGI host. Browser behavior is owned by `packages/builtin-ui/web`, server state crosses only `/api/control/v1`, and the existing release-search request already carries `indexer_ids` without requiring a contract change.

The current client always sends an empty `indexer_ids` list and does not render a destination-query error. The canonical capability also retains a purpose and several phrases describing the removed Jinja implementation or the one-time replacement event. These are specification and presentation-layer gaps; they do not justify a new package, process, persistence path, API, or integration owner.

## Goals / Non-Goals

**Goals:**

- Make the durable canonical specification accurately describe the packaged SPA and its currently supported workflow.
- Preserve the already-approved release-search and safe-error guarantees with the smallest presentation-layer changes.
- Add focused evidence that the browser forwards optional indexer identifiers and blocks Acquisition submission when live destinations cannot be obtained.

**Non-Goals:**

- Expanding the supported UI to Manual workflows, collection mutation, reconciliation, diagnostics, Settings, or About.
- Adding an indexer-discovery endpoint, changing the control OpenAPI document, or changing Prowlarr or qBittorrent module behavior.
- Adding a frontend service, state-management layer, persistent browser storage, compatibility UI, or new dependency.

## Decisions

### 1. Preserve the normative promise and fix the client

The existing specification remains authoritative where the shipped client is incomplete. The change will not weaken “Prowlarr filters” or safe qBittorrent diagnostics to match the current code. Instead, it narrows the ambiguous filter wording to the only filter already represented by the public contract—optional Prowlarr indexer identifiers—and brings the client and tests into conformance.

The rejected alternative is to remove both promises from the specification. That would hide two implementation gaps and would discard approved behavior without evidence of a compatibility or ownership problem.

### 2. Keep indexer filtering inside the existing release request

The release page will expose an optional, clearly labelled presentation control for integer Prowlarr indexer identifiers. It will normalize valid identifiers into the existing `indexer_ids` request array, send an empty array when no filter is supplied, and reject malformed local input with localized semantic feedback before making a search request.

This requires no backend or generated-contract change. Indexer discovery is not added because the control API does not publish an indexer catalog and accepting explicit identifiers satisfies the current requirement at the existing package rung.

### 3. Treat destination lookup failure as a blocking safe error

The release page will render a localized error from the invariant control error code when the live destination query fails, with the existing generic safe fallback for unknown codes. While the query is failed or unresolved, the page will expose neither a stale destination choice nor an actionable Acquisition submission control. A successful retry or a new release selection may load fresh destinations normally.

The control client remains the sole error-normalization boundary. Provider messages, authenticated URLs, integration values, and environment references will not be displayed or stored.

### 4. Synchronize durable prose at the specification boundary

The delta renames the transitional workflow requirement, replaces replacement-era wording in affected full requirement blocks, and reframes the combined compatibility scenario as an explicit upgrade-boundary check while retaining its focused bookmark and legacy-mutation scenarios. The canonical `Purpose` cannot be represented in a delta for an existing capability, so it will be corrected during the later specification-synchronization/archive phase, not by application code or during apply.

The durable purpose will describe an accessible bilingual, bundled browser interface that manages the supported catalog-to-Acquisition workflow exclusively through the same-origin control API.

### 5. Keep ownership and topology unchanged

`packages/builtin-ui/web` remains the only writer for browser presentation state. TanStack Query continues to own server-query state, React owns transient form state, the control API owns session/CSRF and orchestration, and first-party modules continue to own their transports and environment variables. No new runtime component survives the subtraction pass.

## Risks / Trade-offs

- [Operators must know Prowlarr numeric indexer identifiers] → Label the filter as optional, keep all-indexer search as the default, and defer discovery until a separately approved control capability exists.
- [Local parsing could silently alter a requested filter] → Reject malformed values, preserve valid integer values deterministically, and assert the serialized request in focused HTTP tests.
- [A destination error could leave stale client state] → Clear destination selection on each release search/selection transition and hide submission whenever fresh destinations are unavailable.
- [Canonical purpose cannot travel in an existing-capability delta] → Record its exact synchronization responsibility here and verify the canonical file during archive rather than editing it during apply.

## Migration Plan

1. Add focused failing release-page tests for indexer filtering, invalid filter input, and destination-query failure.
2. Implement the minimal release-page and localization changes, then run focused and frontend regression gates.
3. Synchronize the delta and durable canonical purpose through the later OpenSpec synchronization/archive boundary.
4. Rebuild the existing deterministic static assets and publish through the normal application image path. No data, environment, API, or module migration is required.

Rollback is the previous immutable application image or previous packaged static assets; stored data and public contracts are unchanged.
