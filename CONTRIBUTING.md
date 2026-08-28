# Contributing

Thank you for improving Media Finder.

## Language and source of truth

Write repository documentation, OpenSpec artifacts, developer examples, skill instructions, issue text, and pull-request text in English. Russian belongs only in localization catalogs, localization tests, and user metadata fixtures.

OpenSpec is the source of truth for product behavior and architecture. Start any behavior, UX, API, schema, or module-contract change with an OpenSpec proposal and wait for approval before implementation. Safe maintenance that cannot affect behavior may be changed directly.

## Workflow

1. Create a focused branch.
2. Follow the OpenSpec skill-routing contract in `AGENTS.md`. Use `openspec-propose` for a new change and wait for planning approval before `openspec-apply-change` begins implementation.
3. Use `openspec-update-change` instead of editing planning artifacts ad hoc when implementation changes a requirement, scope, design decision, or task.
4. Add or update acceptance scenarios before production behavior, observe the focused RED failure, and implement the minimum change needed for GREEN.
5. Use `openspec-sync-specs` only when canonical specs must change while the change remains active; otherwise let `openspec-archive-change` assess, synchronize, and archive completed work.
6. Run every check documented for the current project stage.
7. Explain user-visible behavior, security impact, migration needs, and RED-to-GREEN validation evidence in the pull request.

Do not manually edit generated `.agents/skills/openspec-*` files. Regenerate them with the pinned CLI when the OpenSpec profile changes.

## Security-affecting changes

Follow the finding lifecycle and exception contract in [SECURITY.md](SECURITY.md). A change that modifies security policy, a scanner, a security gate, an exception, or release-security behavior must run `pnpm security:verify -- --repository OWNER/REPOSITORY` against the exact delivery target. Disabled, malformed, unavailable, or unauthorized GitHub evidence blocks delivery and must not be described as passed. Keep this authenticated live check outside ordinary required pull-request jobs so those jobs retain least-privilege permissions.

## Project skills

The checked-in [project skill catalog](docs/agent-skills.md) is the portable
workflow for architecture, implementation, debugging, review, contracts, module
authoring, verification, publication, and skill maintenance. `AGENTS.md` contains
the trigger table and stable invariants; individual `SKILL.md` files contain the
conditional procedures. Do not copy their bodies into contribution docs.

Use `making-pragmatic-media-finder-decisions` before approving a new ownership
level and again during final subtraction review. Use
`developing-media-finder-changes` for implementation,
`debugging-media-finder-failures` for failures,
`reviewing-media-finder-changes` for review, and
`evolving-media-finder-contracts` for public representations. Use
`maintaining-media-finder-skills` when changing the catalog. Verification,
commit/push/PR/merge, image publication, and stable release work use
`verifying-and-publishing-media-finder`; it derives release identifiers from the
approved release context rather than embedding them in reusable guidance.

## Extension modules

Before adding or changing a module, use the matching project skill:
`adding-metadata-provider`, `adding-release-provider`, or
`adding-download-client`. Before changing normalized metadata, use
`evolving-metadata-schema`.

The [module-authoring guide](docs/module-authoring.md) describes the package,
manifest, registration, lifecycle, conformance, and review boundaries shared by
all three module kinds.

Modules are statically packaged through a pull request. They use specialized public SDK contracts and include a value-free `module.toml`, exact environment declarations, translations, fixtures, and shared capability conformance tests. Manual declares an empty environment contract. Registration factories receive only immutable values declared by their own manifest; integration values and environment references are never persisted. Modules must not access core services, database sessions, HTTP routes, or UI templates.

## Baseline checks

```console
pnpm install --frozen-lockfile
uv sync --frozen --all-groups
pnpm spec:validate
pnpm docs:check
pnpm delivery:test
pnpm delivery:validate
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
pnpm assets:build
git diff --exit-code -- packages/builtin-ui/src/media_finder_builtin_ui/static
```

The built-in UI is an independently buildable workspace package. Code under
`packages/builtin-ui` may import only `media_finder_control` and its web or
localization dependencies; it must never import the backend `media_finder`
package. Run `pnpm ui:dev` to develop the supported catalog, provider, Manual
create/edit/JSON/episode-CSV, release, and Acquisition workflows against
deterministic MSW fixtures without SQLite or external integrations. Supported
SPA bookmarks include `/add/manual` and `/items/{item_id}/edit`; Settings and
About/Credits are intentionally omitted.

Browser tests require the pinned Playwright Chromium installation. The production image is built in GitHub Actions; when Docker is available locally, also run `docker build --tag media-finder:local .`.
