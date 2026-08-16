---
name: maintaining-media-finder-skills
description: Use when creating, editing, evaluating, routing, regenerating, or reviewing project-local Media Finder skills and their agent metadata.
---

# Maintaining Media Finder Skills

Keep stable invariants in `AGENTS.md`, conditional judgment and workflows in
skills, and mechanical facts in tests/CI. Skill prose is not a second OpenSpec.

## One-skill cycle

Complete this cycle for one manually maintained skill before changing another:

1. Define trigger, intended decisions, forbidden decisions, and a reusable
   pressure or application scenario.
2. Record available instruction sources. Distinguish historical observed RED,
   isolated baseline, no-target-skill control, contaminated control, and
   post-skill forward test. A fresh conversation is not automatically isolated.
3. Run the scenario without explicitly loading the target skill. Record the
   actual decision and rationalization. If it already complies, keep that result;
   do not tune the prompt to force failure or claim causality.
4. Write the minimum reusable `SKILL.md` and matching `agents/openai.yaml`.
   Descriptions state triggering conditions, not the workflow summary.
5. Explicitly load the skill and repeat the same scenario. Record the outcome and
   causal limitations. Refine only for an observed gap, then rerun.
6. Validate structure, frontmatter, metadata, portability, routing, and relevant
   OpenSpec/documentation gates. Only then start the next skill.

## Content boundaries

- Keep manually maintained skills concise, imperative, and independent of a
  current product version, release tag, workstation path, selected module, or
  historical incident.
- Put concrete incidents and evaluation transcripts in `docs/agent-skills.md` as
  labeled evidence, not as a skill's purpose.
- Do not copy overlapping upstream catalogs. Adapt only project-specific judgment
  that a clean checkout needs.
- Never manually edit generated `openspec-*` skills; regenerate them with the
  pinned OpenSpec CLI and review the generated diff.
- Update `AGENTS.md` routing only after every referenced skill exists.

## Evidence rules

Literal phrase, substring, or source-text checks can prove inventory, syntax,
metadata, paths, and other mechanical constraints. They cannot prove that an
agent applies judgment. Do not build an LLM eval service, custom prompt runner,
or prose parser for this catalog; portable scenario records and reviewed
forward-tests are sufficient at the current scale.

Do not batch-author skills and test them afterward. Do not call a contaminated
control isolated, a correct control RED, or a post-skill answer solely caused by
the skill when overlapping guidance remained available.

## Handoff

Record skill path, trigger, baseline/control classification, exact reusable
prompt, observed decisions, refinement, post-skill outcome, structural checks,
limitations, and remaining catalog work.
