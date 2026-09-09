## Context

See proposal.md for motivation. The baseline is main `4642604803d66bf6cd0d01fb4efb96ea43391b3f`. Control already declares optional `size` and `seeders`, but `ReleaseCandidate`, Prowlarr mapping, `SelectedRelease` and control projection omit them. `SafeReleaseSnapshot` is persisted and is not an extension point for search facts.

The existing React release page owns a guarded search snapshot and an Acquisition preflight guard. Its attempt factory captures one UUID, but another confirmation constructs a new factory. Detail responses already include acquisitions ordered newest first. Existing UI, Python, Node conformance and hosted browser infrastructure are sufficient; no new verification workflow is needed.

## Goals / Non-Goals

**Goals:** converge the existing producer/consumer chain; make review and retry identity explicit; contain stale asynchronous work within its originating item; retain current privacy and ownership boundaries.

**Non-Goals:** changing persisted snapshots, migration or reconciliation; introducing a state framework, global workflow store, generic request engine or provider-specific core branch; persisting browser tokens or retry payloads; changing package/tool versions.

## Decisions

### Search-only SDK value and coordinated projection

Add a small immutable public `ReleaseSearchMetrics` value in SDK `types.py` with optional `size` and `seeders`, defaulting to unknown. `ReleaseCandidate` gains this value with a backward-compatible default; `SelectedRelease` carries a defensively revalidated copy. Keep `SafeReleaseSnapshot`, private resolution selection, Acquisition persistence and resolve return unchanged. This extra value is justified by one shared numeric contract across runtime and serialized results, rather than duplicating per-consumer field validation.

Use the SDK's existing Pydantic model/field validation mechanisms, with JSON-Schema-compatible integer semantics: accept integral numeric 1.0, reject booleans and numeric strings before coercion, reject fractions, non-finite values and values outside the documented bounds. Update serialized `SerializedReleaseResult`, executable conformance and `_ReleaseContract` schema ownership, not serialized safe snapshots. Core validates even construction-bypassed models before caching. Public validation fails safely; the Prowlarr adapter alone tolerantly normalizes each optional upstream fact to unknown on invalid data. Zero size is unknown because the inspected Prowlarr mapper substitutes zero for absent size; zero seeders is meaningful.

Wire fields remain `size` and `seeders`; control owns matching constraints without importing SDK into the control-contract package. Regenerate SDK schemas, OpenAPI and TypeScript with existing tools. Use the same boundary corpus in Python and Node tests, including omission, null, zero, one, integral float, maximum, maximum+1, negative, fraction, bool, string and non-finite values where representable. Invalid JSON itself is not a valid serialized fixture. Update first-party fixtures and runtime-to-serialized assertions so populated metrics are actually exercised.

Both `SerializedReleaseResult.metrics` and `_ReleaseContract.metrics` use the shared value with an omission-compatible default. Control `ReleaseSearchResult.size/seeders` must reject bool/string before integer coercion as well as enforce bounds. Construction-bypassed SDK values are covered at executable conformance; core cache-boundary validation is implemented and tested in the dependent backend slice.

Alternatives rejected: persisting volatile metrics would enlarge history without a use case; unconstrained numbers lose precision in JavaScript; renaming size or using decimal strings creates an unnecessary browser contract. No contract-major or distribution-version change: updated readers accept omission, while runtime/schema/client ship together in the static image; old strict readers are not forward-compatible by assertion.

### Page-local identity and context

Keep ownership in `release-page.tsx` with an item-keyed inner workflow and an active-lifetime guard for async continuations. Do not add a global store. Fetch context using the existing detail query key and metadata locale fallback used by `media-detail-page.tsx`. Track whether the query was edited and whether initial prefill occurred. Late/refetched context cannot clobber input. Context failure exposes explicit retry; draft editing remains possible, but search and submission require loaded context. Preserve long prefills and show validation above 500 characters rather than silently truncating a work title or expanding the existing SDK bound.

The existing control request ceiling is 512 while the downstream SDK ceiling is 500. This pre-existing mismatch is not changed here: the new UI validates at 500 and cannot send the problematic 501–512 interval. It does not claim that every external request accepted by the existing control model succeeds downstream. Revising that separate request contract is outside this change's metric-response evolution.

Show a return link, title and separately labeled comparison facts in responsive selectable result cards. Format known sizes using localized binary units; retain exact byte count in accessible text. Unknown is an explicit localized value, not zero. Use the existing disclosure primitive/pattern for indexer IDs; its value survives collapse, and invalid hidden input opens the disclosure and receives focus. Existing search snapshot/retry and destination errors remain recoverable.

### Reviewed intent and request identity

Use an accessible modal built from the existing UI dialog pattern. Opening it has no side effect and shows frozen display labels for work, release and destination. Initial focus is on cancellation; Escape cancels and focus returns to the trigger. Confirmation synchronously acquires the existing flight guard and captures an immutable payload, labels and a single attempt factory/key. Inputs cannot change while review or confirmation is active.

Before the first POST, refresh live destinations. A stale destination returns to selection; errors expose existing safe recovery. Check active lifetime after the await and before POST. The user must review a changed destination again. Cancellation after POST is not represented as cancellation of the server operation.

Replace hidden automatic submission retry with an explicit request-retry action. Once a POST is attempted, retain its factory, payload and labels until a definitive result or definitive domain rejection. Network errors, 5xx and unclassified exceptions are uncertain: lock new search/selection on this page and offer the same-attempt retry only. Retrying invokes the exact retained factory without destination preflight, because core checks an existing idempotency key before inspecting a now-consumed token. Navigation remains possible with truthful text that local recovery is lost and the request may have been accepted; do not introduce persistence or promise reload recovery.

Treat `selection_expired` as definitive: clear the actionable token and require fresh search. Treat a definitive stale-destination error as requiring a live destination reload and another explicit review, not uncertain transport recovery. A returned Acquisition (including failed or pending) closes the request attempt: failed offers fresh search; pending explains uncertainty and never offers automatic resubmission. Preserve existing safe diagnostics for other definitive domain errors; do not classify an arbitrary server exception as proof that no submission happened.

The POST can return `download_destination_unavailable` after a successful UI preflight. Core raises this before consuming the token or creating an Acquisition. Discard that rejected frozen factory/payload, clear destination selection, explicitly refetch/replace the live destination list through the existing client, and require a newly selected destination and new reviewed key before POST. The release token remains usable until its normal expiry. Do not assume the current `ControlFailure` exposes `details.destinations`. If the reload fails, submission stays unavailable with safe retry. Preflight rejection follows the same return-to-selection path but sends zero POSTs.

### Outcomes and stale callbacks

Maintain display feedback only in the active item lifetime. On any returned Acquisition, invalidate catalog and `['control', 'media-item', frozenItemId]`, even if the original page is no longer active; do not mutate another page's local state. Abandonment before POST prevents POST; abandonment after POST cannot undo it. Item-keyed mounting clears draft, selected token, destinations, review, attempt and feedback.

Render short localized status labels with separate safe explanations and frozen release/destination labels. In detail, use the first Acquisition from the existing newest-first response; display a compact latest-status section only. No additional query API, ordering layer, history store or progress polling is needed.

### Verification ownership and subtraction pass

SDK/Prowlarr/core/control work owns metric parity; UI consumes generated control types only. Keep the attempt factory narrowly scoped to Acquisition identity. Reuse existing Dialog, disclosure, feedback and status primitives; add no generic orchestration layer. Tests must demonstrate behavior, not source spelling. Synthetic fixtures only; never expose raw provider responses, credentials, magnet links or torrent bytes in logs, screenshots or serialized conformance.

Independent implementation slices may use separate SDK/backend and UI file ownership after these interfaces are fixed. Main owns generated artifacts, shared commands, integration, task completion and acceptance. Reviewers have read-only scope and must identify remaining scenario gaps.

## Risks / Trade-offs

- Optional upstream facts may be missing or inaccurate → preserve unknown and avoid availability/progress claims.
- Old strict readers reject new fields → coordinated image/schema deployment and whole-image rollback; no parallel compatibility shim.
- Navigation or reload loses an unresolved in-memory retry → explain uncertainty and the loss of local retry; durable recovery remains outside this stage.
- Context failures temporarily block searching → explicit retry preserves draft and prevents accidental selection for an unidentified work.
- A browser download timed out in this environment → use existing hosted fixture/browser reports for exact-candidate acceptance, retaining all previous captures; never count an unavailable local browser as passed.

## Migration Plan

No database migration or runtime integration configuration change. Regenerate owning artifacts, run focused RED/GREEN and applicable full gates, obtain independent review and exact-candidate hosted evidence. Synchronize all four deltas and archive only after completed implementation and required verification. Deliver through a non-main PR and protected checks; verify merged main and permitted edge publication. Roll back by restoring the previous complete image, not mixing SDK/schema/UI versions. Stable release remains excluded.
