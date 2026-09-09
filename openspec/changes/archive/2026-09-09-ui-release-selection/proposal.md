## Why

Release selection currently lacks saved-work context and useful comparison data, while submission recovery does not clearly distinguish retrying a request from creating another Acquisition. Stage 5 makes this existing workflow understandable and deliberate, including the missing production path for optional size and seeder information.

## What Changes

- Carry optional, bounded size and seeder metrics from Prowlarr through the public SDK and core to existing control response fields. Keep metrics outside persisted release snapshots.
- Align runtime validation, serialized conformance, schemas, fixtures, OpenAPI and generated UI types in one coordinated deployment.
- Show saved-work identity, an editable title-prefilled query, a return link, comparable release facts and a secondary indexer-ID filter.
- Require a review of the selected work, release and destination before submission. Preserve one frozen payload and idempotency key for request recovery; require fresh search after a returned failed Acquisition.
- Isolate asynchronous work by item and attempt, explain pending/submitted/failed outcomes, and show the latest Acquisition status on the media detail page.
- Cover English/Russian, narrow/wide layouts, keyboard operation and existing recovery regressions.
- No new integration, service, endpoint, migration, persisted metric, download monitoring, acquisition history or reconciliation UI. No general repository-policy or stable-release change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `module-contracts-and-retention`: portable optional search metrics and matching executable/serialized SDK conformance.
- `torrent-acquisition`: ephemeral metric propagation and tolerant normalization of optional Prowlarr facts.
- `browser-control-api`: bounded numeric semantics for existing release-search size and seeders fields.
- `bilingual-web-ui`: contextual search/comparison, reviewed submission, same-attempt recovery, isolated outcomes and latest status.

## Impact

Affected owners are the module SDK, first-party Prowlarr adapter, core release-selection projection, control contracts and built-in UI. Existing contract generators, fixtures, Python/Node/UI tests and hosted browser evidence must advance together. Field names and contract version 1 remain unchanged; new readers accept omitted metrics, but old strict schema readers are not promised forward compatibility. Rollout and rollback use the coordinated application image. No dependency upgrade or persistence change is required.
