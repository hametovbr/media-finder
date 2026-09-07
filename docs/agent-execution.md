# Agent execution environments

Read this procedure before host-dependent commands or when sandbox evidence differs from the supported environment. `AGENTS.md` owns routing and completion gates; this file preserves the host/sandbox procedure. Follow the active tool permissions: repository guidance does not grant host access, authorize an escalation, or permit bypassing a denied action. If the required host mechanism is unavailable, record the gate as blocked and leave the product diagnosis unconfirmed.

Run a verification command directly on the host, with the required authorization,
when its supported boundary depends on capabilities that the restricted sandbox
does not provide. This is required from the first attempt for:

- Playwright and browser/E2E commands that launch Chromium or a local web server,
  including `pnpm ui:browser`;
- the full Python suite and any focused suite that enters Starlette `TestClient`,
  ASGI lifespan, or local-socket behavior;
- `pnpm delivery:test`, whose repository-security tests exercise subprocess and
  timeout behavior, and authenticated live checks such as
  `pnpm security:verify`;
- every independent `uv build --wheel` invocation and any dependency/bootstrap
  command that must reach a package registry;
- Docker, Compose, Buildx, production-image smoke, and local integration-stack
  commands;
- observations of real localhost or LAN listeners, host processes, systemd units,
  IDE IPC sockets, and other already-running host services;
- GitHub delivery operations (`git fetch`/`push`, `gh` API, PR, checks, review,
  merge, workflow, and package queries), and Git index/ref mutations when the
  sandbox exposes `.git` read-only.

Keep deterministic offline checks in the sandbox when they do not cross one of
those boundaries: OpenSpec, documentation, formatting, linting, type checking,
static validators, frontend unit/accessibility tests, and production asset builds.
Use `UV_CACHE_DIR=/tmp/developer-uv-cache` for sandboxed uv commands when the
default user cache is read-only.

For any command not listed above, start in the sandbox. If it fails with a likely
network, DNS, bind, socket, subprocess, browser, Docker, credential, permission,
IPC, or read-only-filesystem limitation, treat the sandbox result as provisional
and rerun the identical command on the host before changing repository code or
tests. Preserve the command, working directory, relevant non-secret environment,
exit status, and candidate SHA across the rerun. Classify an environment
limitation only when the host evidence confirms sandbox isolation or an unavailable
external capability. If the failure reproduces on the host, follow
`debugging-media-finder-failures` and classify the supported-environment evidence
normally. Do not report the gate as passed until the host run succeeds, and do not
infer that a host service, credential, or dependency is broken from sandbox
evidence. Never print tokens, integration values, authenticated URLs, or raw
sensitive upstream payloads while diagnosing either environment.
