---
name: developing-media-finder-changes
description: Use when implementing an approved Media Finder OpenSpec change, migrating a business path, adding a module capability, or when tests or implementation reveal a missing design decision.
---

# Developing Media Finder Changes

Implement one approved behavior path at a time. A refactor is complete only when
the new owner runs production behavior and the superseded path is removed.

## Before editing

1. Confirm apply authorization comes from a user message received after the
   planning artifacts were presented. An implementation request made before the
   artifacts exist is not approval; use `openspec-propose`, present them, and
   stop.
2. Use `openspec-apply-change`; read every reported context file and the current
   task. Proposal approval alone is not apply authorization.
3. Trace the path from delivery adapter through application service, ports,
   persistence or module capability, and public projection.
4. Name the approved scenario or reproduced approved-behavior defect that the
   next test protects. A test cannot create a new requirement.

If a needed capability, compatibility rule, error mapping, ownership boundary,
or architecture rung is absent from the design, stop. Use
`openspec-update-change` and obtain approval before continuing.

## Vertical RED–GREEN slice

1. Add the smallest deterministic test at the owning boundary and observe the
   expected RED.
2. Implement the minimum framework-light domain/application behavior behind an
   existing or approved typed port.
3. Adapt persistence, module runtime, and delivery only at their boundaries.
   Keep module I/O outside database write transactions.
4. Route production composition through the new path.
5. Delete the old service, adapter, branch, shim, import, and duplicate test in
   the same slice. Preserve compatibility only for a verified consumer and with
   an approved retirement rule.
6. Run focused tests, architecture checks, artifacts/conformance when affected,
   then proportional regressions. Mark the task complete only after all required
   behavior is GREEN.

## Completion tests

Do not accept:

- a façade that delegates to the previous monolith;
- two repositories, caches, lifecycle owners, or business paths for one use case;
- concrete module IDs in core;
- generic hooks where one current typed capability is sufficient;
- a compatibility adapter created without users, stored data, or external
  consumers that require it;
- “temporary” source retained without a checked removal task in the same change.

Search for obsolete imports, concrete names, duplicate construction, and old
files. Verify the composition root creates one resource graph and closes it in
reverse order, including partial-construction failure.

## Handoff

Report the scenario implemented, RED and GREEN evidence, removed path, remaining
tasks, exact HEAD/worktree state, and any unavailable verification. Never call a
partial slice complete because the new API shape exists while production still
uses the old owner.

When every apply task is done, use these distinct status fields:

- `Implementation phase: complete`
- `Overall work: incomplete`
- `Next required authorization: verification/archive`

Apply is terminal for the current user turn: do not sync, archive, commit a
delivery candidate, push, or publish. Request the separately authorized
verification/archive action and stop. Overall work cannot become complete until
the applicable OpenSpec closure and protected-branch delivery gates in
`AGENTS.md` finish.
