## Context

See [proposal.md](proposal.md) for motivation. The existing path is already end-to-end: a statically registered metadata module returns `media_finder_sdk.MetadataSearchResult`; core revalidates the value and stores it in the bounded ephemeral selection cache; `MetadataControlService` projects it to `media_finder_control.MetadataSearchResult`; `POST /api/control/v1/metadata-searches` serializes that DTO; and the generated TypeScript contract feeds `MetadataPage`. Selection later consumes the cached SDK value but constructs fetch identity only from provider, external ID, media kind, and locale.

The current production metadata producers are TMDB and Manual. TMDB search responses already contain `overview` and `poster_path`, and its normalization code already owns the fixed `image.tmdb.org/t/p/original` artwork rule. Manual search has no preview requirement. The service is pre-public, has one user and one actual browser consumer (the bundled UI), and ships host, modules, control API, and UI together. There is no persisted preview data or independent release cadence to migrate.

The current UI holds one search result list, one selected radio token, and one selection mutation. The backend consumes the original token when similarity confirmation is required and returns a new opaque token; the client currently retains that token only for Manual confirmation, causing metadata similarity confirmation to reuse the consumed token.

## Goals / Non-Goals

**Goals:**

- Carry optional search-only description and complete poster URL values through the current module → core cache → control → bundled UI path.
- Keep all provider-specific poster-reference interpretation and complete-URL construction inside the producing metadata module.
- Preserve the current metadata selection, exact-duplicate, similarity-confirmation, expiry, saved-item, and optional release-search business path while reducing ordinary selection to one row action.
- Update every deterministic v1 contract artifact and in-repository consumer atomically without adding compatibility machinery.
- Make direct result images and the selection interaction verifiable for failure, security, accessibility, localization, concurrency, and mobile layout.

**Non-Goals:**

- A preview capability, new protocol/factory/runtime accessor, sibling control operation, API v2, compatibility shim, feature negotiation, independently deployed UI support, or mixed-version procedure.
- Preview persistence, database changes, migrations, image proxying/caching/fetching, CSP work, or a generic network-origin policy for future providers.
- Manual-provider preview generation, per-result detail fetches, provider filter chips, a Cancel/Continue footer, add-path or Manual-workflow changes, About/Credits, or unrelated search cleanup.
- A new arbitrary description-length limit or host-side repair of nonconforming module output.

## Decisions

### 1. Enrich the existing v1 DTOs in place

Add `description: str | None = None` and `poster_url: HttpUrl | None = None` to the SDK `MetadataSearchResult`, then regenerate the existing metadata and serialized-conformance v1 schemas and update first-party fixtures. Add equivalent nullable fields to the control `MetadataSearchResult`, regenerate the checked OpenAPI snapshot and generated TypeScript client, and keep the existing gateway method and route.

The SDK fields remain optional/default-null so a producer that does not supply previews, including the current Manual module, still validates. The control response deliberately includes both keys and serializes absence as `null`, matching the existing FastAPI response-model behavior and giving the bundled UI one deterministic shape.

Keep `SDK_VERSION=1.0.0`, `contract_version="1"`, and current manifest ranges unchanged. This is an accepted in-place pre-release contract change: all real producers and consumers are rebuilt together, and no released strict consumer exists. A preview capability or parallel route would add registrations, accessors, fallback states, tests, and lifecycle ownership without protecting a current consumer.

### 2. The metadata module owns the complete poster URL

The shared SDK contract carries only a complete optional `HttpUrl`; it does not carry `poster_path`, image-base settings, size tokens, or another provider-specific reference. Core and control apply their existing defensive model validation and copy the validated value unchanged. The UI renders that exact value and contains no provider-key branch or URL assembly.

TMDB search maps a non-empty `overview` to `description`. It maps `poster_path` only when it satisfies the module's existing `^/[A-Za-z0-9._/-]+$` and no-`..` rule, constructing exactly `https://image.tmdb.org/t/p/original<path>`. Missing/empty overview and missing, path-invalid, or `HttpUrl`-unconstructable poster paths become field absence without suppressing an otherwise valid search result. The implementation may reuse or extract the existing module-local artwork helper, but the URL rule remains owned by the TMDB package.

This absence rule applies while interpreting trusted TMDB upstream data. It does not weaken the SDK/core trust boundary: if any module returns a search-result object that fails the shared DTO contract, existing validation still reports `provider_output_invalid` rather than silently sanitizing it. A future metadata provider defines its own mapping when it is actually added.

### 3. Preview data remains transient and selection remains identity-only

`MetadataCatalogService.search` continues to rebuild each provider result through the SDK model. Because the enriched value is stored whole in the existing bounded ephemeral cache, no second preview cache or persistence model is needed. `MetadataControlService._search_metadata` copies the two preview fields into the existing public DTO.

`select_metadata` continues to derive `MetadataIdentity` only from provider ID, external ID, media kind, and locale. Description and poster URL never affect duplicate detection, similarity decisions, fetching, normalization, immutable revision creation, or catalog persistence. This preserves the existing business path and makes preview expiry identical to selection-token expiry.

### 4. The existing mutation becomes the single owner of row selection

Remove radio state and the footer save action. Each row passes its token directly as the input of the existing selection mutation; the mutation must not read a token that was merely scheduled through a preceding React state update. Its shared pending state is the global single-flight guard. The initiating token is retained only to identify which row displays progress, while all row actions are disabled and guarded against another submission until the request settles. A recoverable error clears pending ownership and re-enables the rows; no cancellation, queue, retry, supersession, or winner arbitration is introduced.

Normal and exact-duplicate success continue to set the existing `savedItem` state and invalidate the catalog query. A `confirmation_required` failure stores the returned confirmation token and opens the existing review modal. Confirming similarity submits that returned token with `confirm_similarity=true`, never the consumed original search token. The control client recognizes the already-supported Manual confirmation kind and the metadata `similarity` kind without changing the backend token model. A genuine `selection_expired` result retains the current localized reset-to-search behavior.

### 5. Rows render untrusted preview text and direct images at the presentation boundary

Each provider group remains a semantic group. Rows show the existing provider, title, and year context, optional description through normal React text rendering, a poster-shaped region, and one localized button. No HTML interpretation is added. Missing images and `onError` failures switch to the established local poster fallback without a remote fallback request.

An available poster is rendered from the complete control value with `loading="lazy"` and `referrerPolicy="no-referrer"`. These attributes reduce unnecessary eager loads and referrer disclosure; they do not hide the direct browser-to-provider request, which is an explicitly accepted TMDB behavior. No proxy, cache, binary endpoint, CSP, or deployment component is added.

Layout and component styling stay within the built-in UI package. Tests cover English/Russian text, keyboard and visible-focus operation, semantic pending/error feedback, poster/description absence and failure, and no horizontal overflow at the supported mobile viewport. Exact spacing and visual density remain implementation details.

### 6. Preserve the existing mutation-security boundary

The existing metadata-search route remains behind JSON media-type, signed-session, CSRF, and same-origin checks. Preview generation occurs only after those checks invoke the gateway. Rejection tests use a counting gateway/cache seam to prove that invalid requests do not call a provider or create search-cache/token state.

The safe-response rule is narrowed only for the validated module-produced public poster URL. Raw provider payloads, raw poster references, authenticated or sensitive URLs, credentials, and upstream error details remain prohibited from control responses and logs.

### 7. Subtraction pass

No new runtime component survives review. The design reuses the existing module DTO, SDK schema generator, catalog validator, ephemeral cache, control DTO/gateway/route, generated client, React page, selection mutation, modal, local poster fallback, and test owners. The rejected preview capability, sibling endpoint, compatibility layer, persistence field, URL service, image mediator, per-row mutation set, and concurrency protocol each add an owner or state machine without satisfying a current requirement.

## Risks / Trade-offs

- [In-place v1 artifacts reject an old strict snapshot] → There is no released or independently operated consumer; regenerate and verify all current schemas, fixtures, OpenAPI, generated types, modules, and bundled UI together. Do not add a shim or version gate.
- [Preview text increases transient memory and render work] → Retain the existing search-result, upstream-response, and 512-entry/15-minute cache bounds; add no unevidenced text cap. Revisit only after a measured defect or a real future producer changes the input profile.
- [A direct poster request reveals the browser's contact with the TMDB CDN and may fail] → This contact is explicitly accepted; use no-referrer and lazy loading, and keep a stable local failure fallback. Do not claim those attributes prevent network contact.
- [A future provider may require a different poster rule] → Keep only the complete URL in the shared contract and require that provider's module to own its mapping; do not generalize the TMDB origin/path rule.
- [Rapid repeated or cross-row activation could send multiple mutations] → Use one mutation owner, pass the token as mutation input, guard every activation from its shared pending state, and verify exact request counts under rapid-repeat and cross-row tests.
- [Similarity confirmation could reuse a consumed token] → Store and submit the new token returned with `kind=similarity`; retain a separate genuine-expiry regression.
- [The public-poster exception could be read as permission to expose other URLs] → Keep the control delta narrow: only the validated search-result `poster_url` is allowed; authenticated, sensitive, raw, and unrelated provider URLs remain forbidden.

## Migration Plan

There is no database, stored-data, deployment, or runtime-state migration. During the separately authorized apply phase, update the SDK/schema/fixtures, TMDB producer, core/control projection, OpenAPI/generated client, and bundled UI in dependency order in one repository candidate. Existing ephemeral selections may be discarded by a normal process restart. No rollout ordering or rollback mechanism is required for this pre-public single-image service.

## Open Questions

None. Exact visual spacing may be adjusted during implementation without changing the specified behavior, ownership, or task breakdown.
