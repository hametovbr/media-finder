## Why

The reusable required verification can currently pass while the built-in UI violates its existing Prettier or Oxlint rules or while its Vitest suite fails. These repository-owned checks already exist and pass locally, so CI should enforce them before later security-tooling changes build on the quality baseline.

## What Changes

- Run the existing `pnpm ui:format`, `pnpm ui:lint`, and `pnpm ui:test` commands in reusable required verification.
- Keep the existing seven protected `verification/*` contexts and reuse their locked Node/pnpm setup.
- Add a focused delivery-policy regression that detects removal or substitution of any required web quality command.
- Do not add another frontend analyzer, a new CI job, a custom orchestration layer, or a separate required accessibility command; accessibility coverage remains part of the full Vitest suite and available through its targeted script.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `deployment-and-delivery`: Make the built-in UI formatting, linting, and full unit-test suite explicit required verification behavior within the existing protected CI contexts.

## Impact

- Affected workflow: `.github/workflows/verify.yaml`.
- Affected policy validation: `scripts/validate-delivery.mjs` and its focused mutation tests.
- Affected contributor guidance only where the local-to-CI command mapping needs to stay accurate.
- No runtime, API, schema, persistence, module-contract, dependency, deployment-topology, or operator compatibility change.
