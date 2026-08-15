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

## Extension modules

Before adding a metadata provider, use `.agents/skills/adding-metadata-provider`. Before adding a download client, use `.agents/skills/adding-download-client`. Before changing normalized metadata, use `.agents/skills/evolving-metadata-schema`.

Modules are statically packaged through a pull request. They must use public contracts, include typed configuration, translations, fixtures, and shared conformance tests, and must not access application database sessions or UI templates.

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
package. Run `media-finder-ui-dev` to develop the complete UI against the
deterministic fake gateway without SQLite or external integrations.

Browser tests require the pinned Playwright Chromium installation. The production image is built in GitHub Actions; when Docker is available locally, also run `docker build --tag media-finder:local .`.
