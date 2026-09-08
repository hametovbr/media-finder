## Why

The approved ui-feedback-recovery implementation has 118 passing local UI tests but cannot complete browser and visual acceptance: pinned Chromium installation times out locally and existing CI retains no browser report or screenshots. The mobile-only workflow needs downloadable evidence from the existing hosted browser job, tied to the candidate actually tested.

## What Changes

- Retain browser test reports and deterministic UI screenshots on both successful and failed verification runs, with explicit provenance and short retention.
- Capture representative recovery states in English and Russian at 360 and 1280 CSS-pixel widths, including pending, error, empty-result and recovered outcomes and keyboard focus.
- Preserve failing test status, all seven required verification contexts and existing least-privilege execution.
- Document a separately authorized pre-archive verification checkpoint/draft PR, distinct from final delivery, so hosted evidence can be obtained before archive without claiming completion or merging unfinished work.
- Product-boundary additions/removals: none. No application routes, APIs, integrations, runtime services, public preview hosting or real-user data collection.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-and-delivery`: downloadable candidate-bound browser evidence and an explicit pre-archive evidence checkpoint procedure that preserves final delivery gates.

## Impact

Affected: `.github/workflows/verify.yaml`, built-in UI Playwright configuration and fixture-only E2E scenarios, delivery validation/tests, and `AGENTS.md`, `docs/agent-execution.md`, and the manually maintained verifying-and-publishing-media-finder skill for checkpoint clarity. No generated OpenSpec skills are edited. Any manually maintained skill change requires the existing skill-maintenance evaluation procedure.

This supports roadmap MF-UIUX-2026-09 stages 1 and 3; it does not close ui-feedback-recovery tasks 5.1-5.3 by itself. Local baseline is a7d27ee64c8736851070fd925df583b91944e8db plus the recorded UI diff; main remains b137f8b2be756e2d657301270d22624f3dbf35a1. Planning does not authorize workflow implementation or checkpoint publication in this turn.
