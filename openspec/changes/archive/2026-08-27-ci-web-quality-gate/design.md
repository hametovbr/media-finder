## Context

See `proposal.md` for motivation and `specs/deployment-and-delivery/spec.md` for the required behavior. The root workspace already exposes `ui:format`, `ui:lint`, and `ui:test`, backed by the built-in UI package's pinned Prettier, Oxlint, and Vitest dependencies. Reusable verification already installs the locked pnpm workspace in the `python` job so it can build deterministic UI assets before building wheels, but it does not execute those three commands.

The protected `main` branch expects exactly seven `verification/*` job contexts, and the repository delivery validator already parses the workflow through a structured YAML representation and enforces those job identifiers. CI has read-only repository contents permission and none of the proposed checks needs a secret or a write permission.

## Goals / Non-Goals

**Goals:**

- Make the three existing root web-quality commands required on every reusable verification invocation.
- Fail with the native Prettier, Oxlint, or Vitest diagnostics and preserve the exact protected job set.
- Make accidental removal or substitution of any command detectable by the existing delivery-policy validator and its mutation tests.

**Non-Goals:**

- Adding or configuring a frontend analyzer, SAST, SCA, secret scanner, or dependency-update service.
- Adding a job, workflow, script alias, custom command parser, or protected-branch context.
- Running the targeted `ui:a11y` command separately because `ui:test` already runs the complete Vitest suite that contains the accessibility cases.
- Creating the broader local-to-CI documentation crosswalk identified by the repository-understandability audit.
- Changing runtime code, APIs, package boundaries, dependencies, workflow permissions, or secret handling.

## Decisions

### Execute the existing root commands in the `python` verification job

Add three separately named steps after `Install locked asset tooling` and before production asset construction. This job already has the pinned Node and pnpm setup and the locked workspace installation required by all three commands, so the change adds no setup, dependency, or check context. Running quality checks before the build and wheel work fails early without weakening the existing build and deterministic-asset gates.

Alternative: add the commands to the `browser` job. That job also has pnpm, but its ownership is the Playwright environment and Chromium installation; combining the complete fast source/unit baseline with the job that exists for browser behavior makes its purpose and timing less clear. Alternative: add a dedicated web-quality job. That would produce the cleanest scheduling boundary but would alter the protected seven-context contract for a change that needs no new owner.

### Keep three explicit commands and native exit behavior

Use separate workflow steps whose `run` values are exactly `pnpm ui:format`, `pnpm ui:lint`, and `pnpm ui:test`. GitHub Actions will stop the job on a non-zero exit, and each tool remains the source of its own diagnostics. No wrapper or aggregate script is needed.

Alternative: add a new `ui:verify` script. It would reduce three YAML lines but create another command surface that contributors and policy validation must maintain without adding behavior.

### Extend the existing structured delivery-policy validation

Use the validator's parsed job steps and existing exact shell-command helper to require each command in the `python` job. Add one mutation test per command that starts from an otherwise compliant fixture and substitutes the command, proving that a printed string or similarly named step cannot satisfy the invariant. This directly protects the approved scenario without interpreting YAML or shell source through new machinery.

Alternative: assert raw workflow substrings. That is less reliable because comments or non-executing text could satisfy it. Alternative: trust the workflow edit without a policy regression. That would allow a later cleanup to reopen the audited gap while all delivery-policy tests remain green.

### Subtraction and ownership

The final design adds only three workflow steps and one invariant in the repository-owned delivery validator with focused tests. The UI package continues to own tool configuration and test content; reusable verification owns when those commands are mandatory. No runtime component, stored state, credential, permission, fallback, compatibility shim, or separate lifecycle is introduced.

## Risks / Trade-offs

- [The required CI critical path becomes longer by the duration of the UI unit suite] → Reuse the already prepared job and do not duplicate installation or add the targeted accessibility subset.
- [A formatting-only failure now blocks changes that previously passed CI] → This is the intended requirement; native Prettier output provides the exact local remediation command.
- [Validator checks could become coupled to workflow presentation] → Validate exact executed commands inside the existing job, not step names or surrounding YAML formatting.
- [Putting web checks in the `python` context makes the context broader than its name] → That context already owns frontend build and asset drift for wheel production; preserving branch-protection compatibility is more valuable than renaming or adding a context.

## Migration Plan

1. Add RED mutation coverage for each missing or substituted web-quality command.
2. Extend delivery-policy validation, then add the three workflow steps so the current repository becomes compliant.
3. Run each web-quality command locally, the delivery-policy tests and validator, strict OpenSpec validation, and the complete repository verification appropriate to CI workflow changes.
4. Publish through the existing protected-branch flow and confirm all seven exact-head and post-merge contexts.

Rollback is a cohesive revert of the workflow, validator, tests, and synchronized specification. No data migration, deployment coordination, or operator action is required.
