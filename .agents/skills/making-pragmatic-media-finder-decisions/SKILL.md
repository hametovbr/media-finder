---
name: making-pragmatic-media-finder-decisions
description: Use when proposing or reviewing Media Finder architecture, adding an ownership boundary, preserving compatibility, or when implementation pressure increases solution complexity beyond an approved design.
---

# Making Pragmatic Media Finder Decisions

Choose the least complex design that satisfies an approved current requirement.
Complexity needs evidence; future flexibility is not evidence.

## Decision sequence

1. State one current goal. Separate verified constraints, compatibility
   obligations, preferences, non-goals, and unknowns.
2. Map the current owner, writer, data flow, trust boundary, failure boundary,
   lifecycle, and rollback.
3. Start at the lowest sufficient rung:

   `configuration → script/adapter → module → package → process/service`

   Move upward only for a proven change in reuse, independent ownership,
   lifecycle, scaling, security, isolation, or release cadence.
4. Compare total ownership cost: state, deployment, observability, recovery,
   migration, security, CI, and operator work.
5. Prefer executing the real behavior or using an existing structured tool over
   analyzing source text. A custom parser, interpreter, platform, or service for
   auxiliary work requires its own approved requirement and ownership decision.
6. Perform subtraction twice: before approval and before merge. For every
   abstraction, fallback, shim, validator, cache, automation step, and process,
   ask which approved scenario fails if it is removed. Remove it when no current
   scenario fails.

## Authorization circuit breaker

Stop apply immediately when the implementation crosses an approved rung, adds a
new owner or business path, expands public scope, or creates a new compatibility
obligation. Use `openspec-update-change` to compare simpler alternatives and
obtain explicit approval before resuming. An earlier apply approval does not
authorize the higher level.

Tests do not expand scope. A new test must trace to an approved scenario or a
reproduced defect in approved behavior. A mutation that demands knowledge of
helper spelling or another language's control flow is a design-review signal,
not automatically a requirement.

## Compatibility decision

Check actual users, stored data, external consumers, published contracts, and
coordinated rollout ability. Preserve compatibility only when evidence creates
the obligation; break it only through an approved, explicit change.

## Required output

Lead with the minimum design. Record decisive evidence, removed complexity,
deferred higher-rung triggers, proportional validation, rollout, and rollback.

## Red flags

- “It may be useful later” without an observable trigger.
- A façade that leaves the old business path active.
- A new process for a package-level ownership problem.
- Repeatedly patching auxiliary machinery instead of executing the invariant.
- Claiming compatibility is required or irrelevant without checking consumers.
