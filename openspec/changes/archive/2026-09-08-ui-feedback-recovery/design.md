## Context

See proposal.md for motivation and the delta spec for acceptance scenarios. Baseline is b137f8b2be756e2d657301270d22624f3dbf35a1. Source inspection establishes missing rendering branches; runtime defect reproductions are still required at the start of apply. Design is included because recovery spans bootstrap and route-local state and needs explicit request/focus decisions before coding.

Current ownership: ControlProvider owns bootstrap/session query state; ApplicationShell owns UI-locale updates; metadata and release pages own search inputs/results. The control client owns transport/CSRF and existing backend owners perform catalog/Acquisition writes. No writer or wire schema changes are necessary.

## Goals / Non-Goals

Goals: implement the delta within existing state owners, with local explicit retry and testable request identity. Preserve typed client boundaries, current successful selection/confirmation behavior and current pending Acquisition semantics.

Non-goals: a global recovery framework, persistent drafts, cross-route search history, new notifications service, refresh of sessions during unrelated mutations, backend retries, a generic error boundary for every application exception, or CI changes. Manual-editor loss prevention and Acquisition idempotency remain later roadmap work.

## Decisions

1. **Handle expected bootstrap errors where the session query lives.** ControlProvider can render a failure view using its existing providers without a session; keep retry local and single-flight. Set bootstrap query retry explicitly to false so each request settlement has a visible outcome. Reuse the existing bootstrap client, query key and loading fallback. Initialize the existing i18n instance from the first supported primary language in navigator.languages (fall back to navigator.language when that list is missing or empty), matching en/ru case-insensitively including regional tags and otherwise using English. This provisional choice adds no persistence or preference writer; after success adopt the returned session. A router error boundary cannot catch its parent; a new global exception-handling platform is unnecessary.

2. **Keep recovery local to the failed operation.** Provider discovery uses its existing query with retry: false and explicit retry and a visible empty-provider state. Locale updates retain confirmed session state until success. Do not invalidate/unmount the current page on failed language updates. Render known errors by invariant code; network/unknown failures use the existing safe generic message. Never render raw error.message, tokens or payloads. Keep diagnostic machine codes unmodified inside error objects, not as translated prose.

3. **Snapshot submitted search inputs.** Pass an immutable submitted query/filter snapshot to each existing mutation rather than reading mutable input inside the request closure. Keep editable fields independent. Retry uses the failed snapshot; the normal search button uses current fields. Show the query in outcome/retry context so these actions are distinguishable. Guard the entire search start synchronously; while pending disable search/retry and result selection. Invalidate old results/selection at new-search start. Ignore abandoned results on unmount and do not allow a late response to become another route's result. Avoid a new state-machine dependency; existing mutation state plus a submitted-input snapshot and small local guard are sufficient.

4. **Preserve workflow safety around searches.** Do not offer a new metadata search while metadata selection/confirmation submission is pending. Do not start a release search while Acquisition submission is pending. This is UI coordination, not a redesign of Acquisition retries. New release search clears only the current release token and destination; prior submitted Acquisition feedback remains historical feedback until a new search outcome replaces it, never an actionable old release. Existing selection-expiry and similarity-confirmation flows remain authoritative.

5. **Use inline feedback with predictable focus.** A standalone bootstrap error has a heading, safe message and retry button; on recovery focus the main region once it mounts. Provider/search/locale messages remain inline; live updates do not move focus out of text entry. Use existing Mantine components and i18n catalogs. Keep controls mounted where practical to preserve focus and wrap long query/message text. A modest shared safe-message renderer is justified only if actual repeated presentation warrants it; no global toast/event infrastructure.

## Risks / Trade-offs

- Retry uses the submitted snapshot while the form is editable -> identify the failed query beside Retry and explicitly test edited-form submission separately.
- A failed session bootstrap has no confirmed preference -> use browser language preferences provisionally and test ordered preferences, regional variants, unsupported/missing values and subsequent session override without inventing storage.
- Clearing old search results reduces continuity -> it prevents mistaken selection after a newer failure; preserve query/filter input and require explicit new selection.
- Query/mutation overlap can cause stale feedback -> test delayed requests, repeated keyboard submission and navigation away; keep recovery scoped to one owner.
- Chromium installation timed out again on 2026-09-08 -> local E2E and visual acceptance remain blocked. Existing baseline CI passed but has no screenshots. No claim of visual readiness follows from planning/unit success.
- Unit axe checks exclude contrast -> measure contrast and inspect actual desktop/mobile renders before delivery; do not call axe alone WCAG conformance.

## Migration Plan

No data migration or new dependency. Apply after artifact approval, extend existing fixtures/tests, rebuild packaged UI, run proportional local gates and exact-head CI. Verify that static output comes only from the build. Roll back through a normal revert/rebuild of the same UI package; existing backend contracts remain compatible.

Delivery cannot be declared ready until required browser and visual evidence exists. If an approved execution path cannot produce it, report blocked. A CI screenshot workflow or change to verification policy needs its own proposal and approval; this proposal does not authorize it. Review and archive are separate lifecycle steps before final delivery.
