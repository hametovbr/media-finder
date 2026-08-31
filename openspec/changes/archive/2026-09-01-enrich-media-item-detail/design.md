## Context

See [proposal.md](proposal.md) for motivation and [specs/bilingual-web-ui/spec.md](specs/bilingual-web-ui/spec.md) for the observable contract.

`MediaDetailPage` already reads one typed `MediaItemDetail` from `/api/control/v1/media-items/{item_id}`. Its `MetadataView` already contains `original_title`, `year`, `genres`, and ordered `artwork`; provider selection and Manual import both persist those values in the current effective revision before returning or navigating to this page. The existing catalog projection chooses the first artwork whose kind equals `poster` case-insensitively, while the metadata-search UI already supplies the informative image, lazy-loading, no-referrer, and local-fallback presentation pattern.

Stored `Artwork.url` is an untrusted complete HTTP(S) value, not a public-CDN guarantee. TMDB constructs its provider URL inside its module, but Manual metadata can contain any URL accepted by the shared `HttpUrl` contract, including loopback, private-network, or userinfo-bearing values. The catalog already gives such stored poster URLs directly to the browser. The approved scope retains that boundary for detail and does not add server-side retrieval, origin filtering, rewriting, or proxying.

The built-in UI may consume only browser control contracts and presentation libraries. No backend, module SDK, concrete provider, persistence, or runtime import may enter this change.

## Goals / Non-Goals

**Goals:**

- Derive a deterministic presentation view from the existing `MetadataView` only.
- Keep poster selection, text cleanup, image failure, responsive layout, and accessible naming independently testable at the detail-page seam.
- Preserve the existing detail query, route, loading/error states, action rules, and hierarchy/history omissions.
- Add no runtime owner beyond the bundled UI component and its static styles/translations.

**Non-Goals:**

- Changing the SDK, normalized metadata, provider behavior, core, storage, control API, OpenAPI, generated client, or add-flow navigation.
- Validating or repairing stored metadata, restricting image origins, removing URL userinfo, hiding direct network contact, or adding an image proxy/cache.
- Sharing one poster abstraction across catalog, metadata search, and detail; their accessibility and layout semantics differ.
- Showing additional normalized fields such as ratings, people, countries, studios, tags, runtime, release date, seasons, episodes, or Acquisition history.

## Decisions

### 1. Keep the change inside `MediaDetailPage`

The page will derive all new presentation state from its existing generated `MediaItemDetail` value. No DTO, endpoint, persistence projection, provider fetch, or cache is added. A small page-local poster presentation unit may isolate failure state, but it remains owned by the detail page rather than becoming a package-wide framework.

**Alternatives considered:** adding a detail-specific `poster_url`, persisting search preview data, or refetching provider metadata. All duplicate values or alter the saved-metadata lifecycle that already reaches the page.

### 2. Reuse the current saved-artwork ordering rule

The page selects the first `metadata.artwork` entry whose `kind` equals ASCII `poster` case-insensitively. It does not rank by language, origin, size, or provider. This matches the existing catalog convention and preserves module/Manual ordering.

Image failure state is scoped to the selected URL so a failed poster for one item cannot force the fallback after navigation to another item or after the query returns a different URL.

**Alternatives considered:** adding artwork ranking or asking core to preselect a poster. Neither has an approved behavior and both create another owner for a convention the UI can apply deterministically.

### 3. Treat the poster as informative but the URL as untrusted

When a poster exists, the page assigns the exact serialized URL to `img.src`, uses `loading="lazy"` and `referrerPolicy="no-referrer"`, and reuses the localized poster-for-title accessible name. It does not parse, rebuild, branch on provider, restrict origin, strip userinfo, or route the request through Media Finder. `no-referrer` is defense-in-depth only and does not imply origin privacy.

When no poster exists or `onError` fires, the page renders the established local poster-shaped MF fallback with `role="img"` and the localized unavailable-for-title name. The fallback contains no remote asset, and changing poster state does not affect textual metadata or actions.

**Alternatives considered:** decorative semantics, an origin allowlist, private-network blocking, URL sanitation, and an image proxy. Decorative semantics understate a poster the user asked to see; the security alternatives change the current contract or introduce a new service and require a separate approved security objective.

### 4. Normalize only presentation whitespace

The page trims `original_title` and every genre label, omits whitespace-only results, and preserves the relative order of the remaining genres. It does not mutate the response, persist repairs, translate genre values, deduplicate labels, or hide an original title that equals the localized title. Year keeps the current optional rendering rule.

Detail-specific English/Russian labels will describe original title and genres; the existing generic poster strings remain suitable for the informative image and fallback.

**Alternatives considered:** displaying raw whitespace, changing provider/Manual validators, and reusing Manual-editor field namespaces. Presentation cleanup contains the behavior locally without changing stored truth or coupling a general detail view to one provider’s editor vocabulary.

### 5. Use a page-local responsive composition

The detail page will use the repository’s existing colocated CSS-module pattern to form a bounded poster column and a `min-width: 0` content column on desktop, then stack or reduce them at the established mobile breakpoint. The poster retains a 2:3 aspect ratio and bounded width; long metadata can wrap without creating document-level horizontal overflow. Existing actions stay in the content flow and remain keyboard operable.

**Alternatives considered:** global shell styling or a new design-system component. Both broaden ownership without another current consumer.

### 6. Verify behavior through existing UI seams

Implementation follows test-driven development. Focused component tests first express rich values, whitespace filtering, poster ordering and exact attributes, absent/failed fallback, URL-scoped failure, provider/Manual action rules, and existing error behavior. Existing accessibility coverage gains English/Russian detail cases. Existing Playwright routing gains deterministic poster interception, fallback, mobile overflow, and action-availability checks. Contract, package-boundary, build, and isolated-wheel gates prove that the change did not cross into backend or contract ownership.

No live provider, external image origin, database mutation, or new test service is needed.

### 7. Subtraction pass

No new runtime component, dependency, API field, schema, migration, provider rule, cache, proxy, compatibility path, deployment step, feature flag, or shared abstraction survives review. The only new static ownership is detail presentation styling and any detail-specific locale keys beside the existing component and tests.

## Risks / Trade-offs

- [A stored Manual poster can contact loopback, a private network, or a userinfo-bearing origin] → Preserve the explicitly approved current direct-load boundary, send no referrer, never server-fetch the URL, and document that the request is not private or origin-restricted.
- [A remote image can fail or be blocked by the browser] → Replace only the image with the stable local fallback and retain every textual field and action.
- [Whitespace-only Manual values could create empty metadata regions] → Trim at presentation time, filter empty results, and cover mixed valid/blank genres deterministically.
- [Failure state could leak across item navigation] → Scope failure to the selected URL and test a URL change after failure.
- [Long titles or genre labels could overflow the richer layout] → Constrain grid children with `min-width: 0`, allow wrapping, and verify document width at the supported mobile viewport.
- [A UI-only change could accidentally drift the control contract or package graph] → Run generated-contract, architecture-boundary, production-build, and isolated-wheel checks even though no contract edit is planned.

## Migration Plan

There is no database, schema, stored-data, provider, API, deployment-order, or runtime-state migration. The bundled static UI ships with the same server package as today. Rollback is a normal revert of the UI/spec change; no data restoration, compatibility shim, or cleanup operation is required.

## Open Questions

None. Exact spacing, poster width within the bounded responsive layout, and genre text-versus-badge styling are implementation details that do not change the specification or task order.
