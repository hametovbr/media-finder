# Contributing

Thank you for improving Media Finder.

## Language and source of truth

Write repository documentation, OpenSpec artifacts, developer examples, skill instructions, issue text, and pull-request text in English. Russian belongs only in localization catalogs, localization tests, and user metadata fixtures.

OpenSpec is the source of truth for product behavior and architecture. Start any behavior, UX, API, schema, or module-contract change with an OpenSpec proposal and wait for approval before implementation. Safe maintenance that cannot affect behavior may be changed directly.

## Workflow

1. Create a focused branch.
2. Use the generated OpenSpec workflow skill appropriate to the change.
3. Add or update acceptance scenarios before production behavior.
4. Implement test-first and keep commits scoped to one reviewed stage.
5. Run every check documented for the current project stage.
6. Explain user-visible behavior, security impact, migration needs, and validation evidence in the pull request.

Do not manually edit generated `.agents/skills/openspec-*` files. Regenerate them with the pinned CLI when the OpenSpec profile changes.

## Extension modules

Before adding a metadata provider, use `.agents/skills/adding-metadata-provider`. Before adding a download client, use `.agents/skills/adding-download-client`. Before changing normalized metadata, use `.agents/skills/evolving-metadata-schema`.

Modules are statically packaged through a pull request. They must use public contracts, include typed configuration, translations, fixtures, and shared conformance tests, and must not access application database sessions or UI templates.

## Baseline checks

```console
pnpm install --frozen-lockfile
pnpm spec:validate
```

Additional Python, browser, and container checks will be documented as those stages are implemented.
