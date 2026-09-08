## 1. Bootstrap and provider discovery

- [ ] 1.1 Reproduce the approved bootstrap and provider-discovery failure scenarios with focused failing tests, including provisional browser-language selection (ordered preferences, regional variants, missing/unsupported values and session override), no automatic discovery retries, repeated retry, requested-route preservation, safe messages, empty providers and the Manual alternative.
- [ ] 1.2 Implement local bootstrap failure/pending/retry rendering and recovery focus in ControlProvider; verify single-flight and no unrelated mutation replay.
- [ ] 1.3 Implement provider loading/error/empty states and explicit retry; preserve query and route and block unavailable provider search. Make the focused tests pass.

## 2. Metadata search recovery

- [ ] 2.1 Add and observe failing tests for initial versus empty results, safe failure, submitted-query feedback, retained editable input, retry snapshot versus edited submission, old-result invalidation, repeated activation and abandoned responses.
- [ ] 2.2 Implement the metadata search states and immutable submitted snapshot using existing page ownership; prevent search during metadata selection/confirmation submission. Verify focused tests and existing selection/similarity-confirmation regressions.

## 3. Release search recovery

- [ ] 3.1 Add and observe failing tests for the search scenarios from task 2.1 on release search, including indexer filters, selection/destination reset and pending Acquisition coordination.
- [ ] 3.2 Implement release search feedback, safe retry and request guards; preserve input and existing Acquisition semantics, and never replay Acquisition submission through search retry. Verify focused tests and existing selection-expiry/submission regressions.

## 4. Interface language and accessible feedback

- [ ] 4.1 Add and observe failing tests for failed locale updates and explicit single-flight retry: retain confirmed language, route and fields; apply returned locale/document language only on success; never replay unrelated mutations.
- [ ] 4.2 Implement locale recovery in the existing shell owner and make the focused tests pass, preserving the metadata-locale contract.
- [ ] 4.3 Add focused failing assertions for missing RU/EN messages, semantic alerts/status and focus behavior across the approved recovery scenarios; complete shared catalog changes and presentation, then verify these assertions and UI accessibility regressions.

## 5. Verification and handoff

- [ ] 5.1 Extend the existing browser scenarios for keyboard recovery, delayed/repeated requests and navigation abandonment. Run them with the pinned browser on an authorized execution path; record unavailable execution as blocked.
- [ ] 5.2 Inspect desktop and 360 CSS-pixel renders in RU/EN with long queries; record screenshots, overflow, visible focus, contrast and target-size evidence. Resolve defects within scope; do not treat axe alone as visual acceptance.
- [ ] 5.3 Run strict OpenSpec validation and applicable repository gates: documentation, UI format/lint/type/tests/a11y/browser/contract/build and delivery policy checks. Regenerate packaged static assets only through the build; inspect the final diff for unintended contract or generated changes.
- [ ] 5.4 Obtain independent review of scenario coverage, recovery ownership and workflow safety; resolve findings and rerun affected checks. Record candidate, task/scenario evidence and remaining gates in the persistent roadmap. Stop at apply handoff for separately authorized synchronization/archive and subsequent exact-head CI/PR delivery.
