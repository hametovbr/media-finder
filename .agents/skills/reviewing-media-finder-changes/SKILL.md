---
name: reviewing-media-finder-changes
description: Use when reviewing a Media Finder design, implementation slice, pull request, auxiliary CI mechanism, package boundary, module, contract, or release preparation.
---

# Reviewing Media Finder Changes

Review necessity before local correctness. Correct code for an unnecessary or
unapproved mechanism is still the wrong change.

## Review order

1. Pin the exact diff, HEAD, OpenSpec change, task, and approved scenarios. State
   what evidence is unavailable or belongs to another commit.
2. Check necessity and scope. For every new component, abstraction, fallback,
   compatibility path, automation layer, and process, ask which approved scenario
   fails without it. Request subtraction when the answer is absent or hypothetical.
3. Check ownership: one writer, one business path, one lifecycle owner, explicit
   composition, dependency direction, partial-construction cleanup, and reverse
   shutdown. Reject façade-only decomposition and compatibility shims without a
   verified consumer.
4. Check public boundaries: existing wire behavior, OpenAPI/JSON Schema, SDK DTOs
   and errors, manifests, persistence history, serialized fixtures, and current
   consumers. Internal refactors do not silently change external contracts.
5. Check hostile boundaries: bounded input, result count and fan-out, finite
   portable values, URL/GUID safety, redaction, timeout ambiguity, correlation,
   transaction duration, and runtime/executable/serialized parity.
6. Only then review implementation correctness, concurrency, error handling,
   tests, readability, and maintainability.

## Auxiliary complexity audit

Apply the same ownership test to scripts, validators, workflow checks, fixtures,
and test harnesses. Prefer executing real behavior or consuming structured data.
If helper code starts interpreting another language, reconstructing control flow,
or accumulating bypass-specific mutations, stop and compare removal or a
maintained structured tool before reviewing the next patch.

Tests must protect approved behavior. A source-spelling mutation, private symbol
inventory, or literal prose check is not behavioral evidence unless the source
form itself is the approved contract.

## Findings

- **Critical:** exploitable security/data-loss issue or release must stop now.
- **Important:** approved behavior, architecture, contract, lifecycle, or
  reproducibility is materially wrong; merge blocks.
- **Minor:** maintainability or clarity debt that does not invalidate the change.

For each finding, cite the concrete path/behavior, impact, reproduction or
reasoning, and the smallest correction. Do not prescribe a larger redesign than
the requirement needs.

## Completion verdict

End with Critical/Important counts, scenario coverage, proportional verification,
auxiliary-complexity result, unresolved evidence, and a clear merge yes/no. A
green suite does not override an ownership, contract, or necessity failure.
