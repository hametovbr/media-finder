# Modular Core Architecture Handoff — 2026-08-16

## Purpose

This is an intentional intermediate checkpoint for the active OpenSpec change
`establish-modular-core-architecture`. Work paused because the workstation must
be restarted. The branch is safe to continue from another device, but the
current Task 8.3 diff is intentionally incomplete and one delivery gate is RED.

## Git and OpenSpec state

- Branch: `refactor/modular-core-architecture`
- Last fully completed commit before this checkpoint: `3864161 ci: verify the complete modular workspace`
- Active change: `openspec/changes/establish-modular-core-architecture`
- Completed through Task 8.2.
- Task 8.3 is in progress and must remain unchecked until the production image
  build, verifier, delivery gates, and independent review are all GREEN.
- Tasks 8.4–8.6 and 9.1–9.4 have not started.
- No pull request has been opened for this branch yet.

Recent completed phase commits, newest first:

```text
3864161 ci: verify the complete modular workspace
f8cd09f build: enforce reproducible workspace artifacts
7f24f89 feat: serialize module conformance contracts
e30b819 test: prove real browser control conformance
91e2215 test: isolate built-in ui package
5703934 feat: freeze processor api contract
11c1ccf refactor: split module runtime bounded context
baa14c0 refactor: remove legacy server compatibility layer
2d6b76c refactor: centralize server composition lifecycle
3e2fc2a refactor: decompose core control orchestration
```

## Accepted Task 8.3 direction

The Docker image must be built from all nine workspace wheels, not from editable
or copied workspace import paths. External runtime dependencies must come from
the current lock and retain artifact hashes. The runtime remains one non-root
process with UID/GID 10001, `/data` persistence, and both `builtin` and
`disabled` UI-mode smoke coverage.

The current Dockerfile implements the intended build direction:

- builds the nine workspace distributions sequentially as wheels;
- exports external requirements with `uv export --locked` and hashes intact;
- installs external requirements into a fresh `/opt/venv` with
  `--require-hashes`;
- installs local wheels with `--no-deps`;
- copies only `/opt/venv` into the runtime stage;
- uses `python -m media_finder_server` as the sole application entrypoint.

The sequential wheel loop is intentional. A local Windows reproduction found a
concurrent `uv build --all-packages` output-directory race (`EACCES`/`EEXIST`).

## Simplification decision made immediately before the pause

Do **not** keep or complete the custom shell parser currently left in
`scripts/validate-delivery.mjs`.

The earlier implementation embedded a large Python heredoc in
`scripts/smoke-container.sh`. Static validation then grew into a small shell
tokenizer and compound-command reachability parser. Review repeatedly found new
valid shell forms that bypassed it. The accepted simplification is:

1. Keep the runtime checks in the standalone `scripts/verify-image.py` file.
2. Unit-test its pure snapshot validation in `tests/test_verify_image.py`.
3. Have `scripts/smoke-container.sh` execute the verifier in the running
   container with the simple top-level command currently present:

   ```sh
   docker exec -i "$container_name" python -I - < scripts/verify-image.py
   ```

4. Keep the JavaScript delivery validator narrow. It should verify the verifier
   file exists, the smoke script invokes it, the image job executes the smoke
   script, and the main Dockerfile invariants/dataflow hold. It must not parse or
   attempt to prove arbitrary shell reachability.
5. Run the real image smoke in GitHub Actions; that execution is the authoritative
   proof that the verifier runs.

## Current tracked WIP

```text
M  Dockerfile
M  openspec/changes/establish-modular-core-architecture/tasks.md
M  scripts/smoke-container.sh
M  scripts/validate-delivery.mjs
M  scripts/validate-delivery.test.mjs
A  scripts/verify-image.py
A  tests/test_verify_image.py
A  docs/handoffs/2026-08-16-modular-core-architecture.md
```

`scripts/verify-image.py` currently validates:

- all nine expected distributions;
- module and distribution origins under `/opt/venv`;
- one lockstep product version;
- no `/build`, `/app/apps`, `/app/packages`, or source-bearing `.pth` leakage;
- packaged UI templates/static files/EN+RU catalogs;
- module manifests and conformance/runtime fixtures;
- packaged Alembic resources and head `0001_clean_core`;
- exactly one `python -m media_finder_server` process.

`tests/test_verify_image.py` covers the successful snapshot and focused failures
for missing distributions, bad origins, version drift, source leakage, missing
resources, wrong migration head, and process count.

## Exact verification state at pause

Fresh command:

```powershell
.\.venv\Scripts\pytest.exe -q tests\test_verify_image.py --no-cov
```

Result:

```text
12 passed in 0.23s
```

Fresh command:

```powershell
$env:CI='true'
$env:PATH='C:\Users\arioh\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;' + $env:PATH
pnpm delivery:validate
```

Result: **RED**, intentionally captured in this checkpoint:

```text
ReferenceError: shellOperatorAt is not defined
```

This failure is caused by the interrupted simplification: the obsolete shell
parser still exists in `scripts/validate-delivery.mjs`, while one of its helpers
has already been removed. Do not repair that parser. Delete the parser and move
the validator to the narrow verifier-file contract described above.

Docker and Bash executables were unavailable from the current Windows session.
The actual `docker build` and `scripts/smoke-container.sh` execution therefore
remain unverified locally and must pass in GitHub Actions before Task 8.3 is
checked.

## Immediate continuation steps

1. Read `AGENTS.md` and resume the `openspec-apply-change` workflow for
   `establish-modular-core-architecture`.
2. Keep Task 8.3 unchecked.
3. Remove `shellTokens`, `functionBody`, `executableHereDocuments`, and related
   reachability-only helpers from `scripts/validate-delivery.mjs`.
4. Remove the shell grammar/compound-block mutation helpers and cases from
   `scripts/validate-delivery.test.mjs`.
5. Add focused RED mutations for the simpler contract:
   - missing `scripts/verify-image.py`;
   - smoke no longer invokes the exact verifier;
   - verification workflow no longer runs `tests/test_verify_image.py`;
   - Docker loses wheel-only, lock/hash, final-stage, non-root, or entrypoint
     invariants.
6. Add `tests/test_verify_image.py` to an existing GitHub verification job and
   make the delivery validator require that real pytest invocation. Preserve the
   same seven protected `verification/*` contexts.
7. Run at least:

   ```powershell
   .\.venv\Scripts\pytest.exe -q tests\test_verify_image.py --no-cov
   pnpm delivery:validate
   pnpm delivery:test
   .\.venv\Scripts\ruff.exe format --check scripts\verify-image.py tests\test_verify_image.py
   .\.venv\Scripts\ruff.exe check scripts\verify-image.py tests\test_verify_image.py
   .\.venv\Scripts\mypy.exe
   pnpm spec:validate
   git diff --check
   ```

8. Run `docker build -t media-finder:ci .` and
   `bash scripts/smoke-container.sh` where Docker is available. If only CI has
   Docker, push the completed Task 8.3 commit and treat the existing image job as
   the authoritative execution gate.
9. Request a fresh independent Task 8.3 review. Only after PASS mark Task 8.3
   complete and commit it as its own phase.

## Remaining plan after Task 8.3

- **8.4:** derive Compose/environment documentation from first-party
  `module.toml` manifests; remove stale persisted-environment-reference claims.
- **8.5:** add English architecture and module-authoring documentation.
- **8.6:** update `AGENTS.md`, existing project skills, add
  `adding-release-provider`, and add deterministic project-skill validation.
- **9.1–9.4:** full frozen verification, both UI-mode end-to-end smokes, final
  prohibited-dependency/legacy-path/artifact scan, scenario-to-evidence audit,
  independent final review, spec synchronization, and archive.
- After the entire change is complete: push final commits, open a PR, wait for
  all seven required GitHub checks, merge, and verify the resulting main branch.

## Notes

- The ignored `.superpowers/sdd/implementation-plan/task-8-3-report.md` contains
  earlier RED/GREEN/review history but is not part of this checkpoint commit.
- Do not resurrect the deleted legacy `media_finder` compatibility tree.
- Do not add a second container, dynamic runtime plugin discovery, cross-origin
  browser API, or persisted integration configuration.
