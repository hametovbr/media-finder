## 1. Portable search metric contract

- [x] 1.1 Add focused failing SDK runtime, executable and serialized conformance tests for omission, portable integer boundaries and SDK construction-bypassed invalid metrics in executable conformance, mapped to Portable release search metrics scenarios. Core-boundary tests belong to 2.1. Record RED before production edits.
- [x] 1.2 Implement the immutable search-only SDK metric value, backward-compatible candidate defaults and shared `SerializedReleaseResult.metrics` / `_ReleaseContract.metrics` ownership with omission-compatible defaults; prove GREEN without changing safe snapshots or private artifact handling.
- [x] 1.3 Regenerate SDK schemas with `uv run media-finder-sdk-schema --output schemas/module-sdk/v1`; add matching Node boundary-corpus tests, prove RED against the old schema and GREEN against generated artifacts; run SDK and module-conformance regressions.

## 2. Real provider-to-control pipeline

- [x] 2.1 Add failing Prowlarr normalization and populated fixture parity tests, plus core defensive validation, gateway and HTTP projection tests for Ephemeral release comparison facts and Bounded release comparison projection. Include evidence that persisted snapshots do not gain metric fields.
- [x] 2.2 Implement Prowlarr optional-field normalization and core candidate/selected-result propagation; preserve valid peer metrics and selectability when an optional fact is bad. Run targeted Prowlarr and acquisition regressions to GREEN.
- [x] 2.3 Tighten existing control `ReleaseSearchResult.size/seeders` with matching bounds and before-coercion bool/string rejection, project SDK facts and regenerate OpenAPI/TypeScript using `uv run python scripts/generate-control-openapi.py` and `pnpm --filter @media-finder/builtin-ui contract:generate`. Verify gateway/HTTP/OpenAPI, package boundaries and browser-security conformance.

## 3. Contextual comparison UI

- [x] 3.1 Add failing release-page tests for Contextual release search and Comparable release results: untouched/edited/late/locale prefills, failed context retry, 500-character validation, item reset, unknown versus zero, exact accessible byte count including the portable maximum and advanced-filter retention/reveal.
- [x] 3.2 Implement item-local context, safe prefill, return link, labeled release facts and accessible advanced filters; update existing MSW context fixtures and EN/RU strings. Run focused tests to GREEN while retaining existing search-recovery assertions.

## 4. Review, recovery and latest status

- [x] 4.1 Add failing review and attempt tests for cancel/Escape/focus, repeated confirmation, preflight destination rejection/abandonment with zero POST, and server 409 destination races after preflight. Assert explicit list reload, retained release token, discarded old intent and newly reviewed destination/key; also exact frozen payload/key reuse after network/5xx errors without new preflight or automatic POST, and no fresh attempt while uncertain.
- [x] 4.2 Implement reviewed intent and explicit same-attempt retry with synchronous admission and active-lifetime guards. On definitive stale-destination POST rejection, discard the old factory/payload, clear destination, refetch the live list and require new review/key; keep submission unavailable on reload failure. Verify expired tokens require fresh search and returned failed/pending outcomes differ from request exceptions.
- [x] 4.3 Add failing late-response/detail tests for per-item feedback isolation, affected-item cache invalidation even after navigation, latest-only status with release and destination and separate pending/submitted explanations; assert submission feedback uses the frozen release and destination labels. Implement to GREEN with EN/RU content and no history/progress/reconciliation UI.

## 5. Browser evidence and integration acceptance

- [ ] 5.1 Extend existing fixture browser scenarios for EN/RU at 360/1280: comparison with long/unknown/zero facts, review/cancel/focus containment, uncertain retry, returned pending/failed/submitted and latest detail outcome. Retain all existing Manual and recovery captures. Observe new behavioral RED before accepting GREEN.
- [ ] 5.2 Run strict OpenSpec/docs/delivery validation, applicable Python format/lint/type/full tests, SDK/Node conformance, UI format/lint/type/unit/a11y/contract/build and package/security checks using repository-pinned commands. Regenerate packaged assets through the owning build only.
- [ ] 5.3 Obtain exact-candidate browser execution and inspect new screenshots directly; if the pinned local browser remains unavailable, use the existing non-final hosted verification checkpoint. Record provenance, failures, skips and unavailable gates accurately.
- [ ] 5.4 Obtain independent scenario/contract/ownership review, fix all material findings with focused RED/GREEN and rerun affected regressions. Verify no persistence change, private-data exposure or unnecessary runtime mechanism; record final verification and remaining delivery gates.
