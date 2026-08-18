## Why

Media Finder's architecture and delivery work currently depends on skills installed on one workstation, and the session history shows that generic architecture, TDD, and review guidance did not reliably stop auxiliary tooling from escalating into an unnecessary custom shell parser. The repository needs a self-contained agent workflow that preserves the accepted modular architecture across devices and makes any increase in architectural complexity a new approval boundary.

## What Changes

- Add a project-owned, cross-device skill catalog for architecture decisions, implementation, debugging, review, contract evolution, verification/publication, release, and skill maintenance.
- Keep every manually maintained skill reusable across product versions and future incidents: release identifiers and historical failures belong in release plans, evaluation scenarios, and reference documentation rather than skill purpose or mandatory workflow text.
- Strengthen the existing metadata-provider, release-provider, download-client, and metadata-schema skills with the bounded-input, wire-compatibility, and executable/serialized parity lessons found during final review.
- Keep the generated OpenSpec lifecycle skills unchanged and make `AGENTS.md` the concise routing and invariant contract for all project-local skills.
- Record a repository-local historical audit, upstream provenance, and reusable pressure scenarios without adding an LLM evaluation service or source-text validator.
- Record evaluation provenance explicitly: distinguish historical observed failures, fresh controls without the target skill, genuinely isolated baselines, contaminated controls that can see overlapping global or repository guidance, and post-skill forward tests; never claim causality that the setup cannot establish.
- Add a hard complexity circuit breaker: crossing from a simple helper to a parser, platform, service, process, or other higher ownership rung stops apply work and requires an updated OpenSpec design plus explicit approval.
- Extend the existing release workflow guidance with a version-independent procedure, then use that procedure to prepare, publish, and verify Media Finder `v0.2.0` only after the workflow change and a separate lockstep version-bump PR are merged to `main`.
- Preserve the current application runtime, package graph, database schema, HTTP contracts, seven required verification contexts, and one-image deployment.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `modular-application-architecture`: Require a repository-owned architecture decision and review workflow, evidence-based complexity rungs, a mandatory subtraction pass, and approval renewal when implementation crosses into a more complex architecture category.
- `deployment-and-delivery`: Require a portable, version-independent project skill catalog, pressure-scenario validation, exact-commit verification/publication discipline, and a lockstep stable-release procedure; this change then applies that procedure to `v0.2.0` after merge.

## Impact

- Affects `.agents/skills/`, `AGENTS.md`, contributor documentation, OpenSpec planning/canonical specifications, and the release-preparation metadata for `v0.2.0`.
- Adds no production dependency, process, service, parser, database migration, HTTP endpoint, package boundary, or runtime configuration.
- Uses the existing GitHub Release and GHCR workflows; the only release-time source change is a separate lockstep product-version update and regenerated manifest-bound conformance metadata.
