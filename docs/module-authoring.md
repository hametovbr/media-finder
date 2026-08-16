# Module authoring

Media Finder modules are statically reviewed Python packages that implement one
public capability kind. They are built into the common image and execute in the
same process as core. The module SDK provides replaceability and contract
validation; it does not provide a security sandbox or runtime plugin system.

Use this guide together with the project skill for the selected kind and the
OpenSpec workflow in `AGENTS.md`.

## Supported module kinds

| Kind | Public registration | Required operations | Current first-party package |
| --- | --- | --- | --- |
| Metadata provider | `MetadataProviderRegistration` | search, fetch, normalize, retention | Manual, TMDB |
| Release provider | `ReleaseProviderRegistration` | search, resolve, at least one artifact kind | Prowlarr |
| Download client | `DownloadClientRegistration` | destinations, submit, correlation, at least one artifact kind | qBittorrent |

Metadata providers may additionally declare `metadata-edit` and supply a typed
editor factory. Optional behavior is represented by a named SDK capability, not
an untyped hook map.

## Package shape

A repository module is one uv workspace distribution:

```text
packages/modules/<kind-name>/
├── pyproject.toml
├── src/<import_package>/
│   ├── __init__.py
│   ├── registration.py
│   ├── module.toml
│   ├── py.typed
│   ├── fixtures/conformance.json
│   └── translations/{en,ru}.json
└── tests/
```

Transport, provider/client, normalization, retention, and editor files are added
only when that module owns the behavior. Do not copy browser templates, static
assets, core services, or persistence models into a module.

The wheel must depend directly on `media-finder-module-sdk` and only its own
implementation libraries. It must not depend on `media-finder-core`,
`media-finder-control-contracts`, `media-finder-builtin-ui`, the server host,
SQLAlchemy, Alembic, or a sibling module.

## Public entry point

The import package exposes only its supported public API, normally:

```python
from .registration import registration

__all__ = ["registration"]
```

`registration()` returns the typed registration for the module kind. The
registration contains the parsed immutable manifest and factories for declared
capabilities. Core never imports the concrete provider/client class and never
branches on the concrete module ID.

The server host is the only package that imports concrete registrations. Add the
registration explicitly to
[`apps/server/src/media_finder_server/modules.py`](../apps/server/src/media_finder_server/modules.py).
If acquisition should select a new release provider or download client, change
the explicit host selection in the same reviewed change; insertion order must
never select behavior.

## `module.toml`

`module.toml` is the canonical, value-free module declaration. It contains:

- `module_id`: stable lowercase identity accepted by the SDK;
- `module_kind`: `metadata-provider`, `release-provider`, or `download-client`;
- `module_version`: the product/module SemVer, kept in lockstep for first-party modules;
- `sdk_compatibility` and `contract_version`;
- translated name and attribution keys;
- the complete capability set;
- the exact environment variable declarations.

Example:

```toml
module_id = "example-release"
module_kind = "release-provider"
module_version = "0.1.0"
sdk_compatibility = ">=1,<2"
contract_version = "1"
name_key = "module.example_release.name"
capabilities = ["search", "resolve", "magnet"]
translation_keys = [
  "module.example_release.name",
  "module.example_release.environment.url",
  "module.example_release.environment.token",
]

[[environment]]
name = "EXAMPLE_RELEASE_URL"
required = true
secret = false
description_key = "module.example_release.environment.url"

[[environment]]
name = "EXAMPLE_RELEASE_TOKEN"
required = true
secret = true
description_key = "module.example_release.environment.token"
```

Environment declarations are part of the public module contract. The runtime
passes a `ResolvedModuleEnvironment` containing only declared names. A module
must not read `os.environ`, accept arbitrary configuration maps, persist values
or `env:` references, or expose secrets through DTOs, exceptions, URLs, logs,
fixtures, or translations. A configuration-free module declares an empty
environment list; it does not invent placeholder variables.

## Capability implementation

Implement the relevant protocols exported by `media_finder_sdk`:

- accept and return only SDK DTOs at the boundary;
- defensively bound upstream responses, result counts, strings, selections, and
  artifacts before constructing public values;
- translate upstream and validation failures to `ModuleError` with a stable
  category, code, and safe details;
- create module-owned HTTP clients and cookie jars inside the registration
  factory;
- reject unsafe URLs before credentials are attached;
- make `close()` idempotent and release all module-owned resources;
- perform no database, UI, core-service, or process-global lifecycle work.

Networked factories receive only `ResolvedModuleEnvironment` and create their
own transport. Do not accept a global HTTP client or DI container. The root
`ModuleRuntime` validates an instance before caching it, closes failed and losing
concurrent attempts, and owns final shutdown.

## Executable conformance

Each module package runs the SDK suite for its kind:

- `assert_metadata_registration_conforms` and, when declared,
  `assert_metadata_editor_registration_conforms`;
- `assert_release_registration_conforms`;
- `assert_download_registration_conforms`.

Tests must cover successful operations, the exact declared environment,
standardized errors, redaction, limits, and double-close lifecycle. Networked
modules additionally test origin/path confinement, timeout/error mapping, and
isolated cookies. Use deterministic fake transports; never contact a real
integration in conformance tests.

## Serialized conformance fixture

`fixtures/conformance.json` is the language-neutral characterization artifact
for the same public behavior. It is validated against
`schemas/module-sdk/v1/conformance.schema.json` by the independent Node validator.
The fixture binds to the raw manifest hash and records:

- manifest identity, kind, version, capabilities, and value-free environment;
- representative successful cases and retention/editor behavior where applicable;
- every declared stable failure and exact safe error data;
- bounded safe snapshot/artifact descriptors;
- synthetic redaction probes that executable package tests inject through real
  module operations.

Do not serialize real credentials, private release selections, magnet URIs,
torrent bytes, authenticated download URLs, or raw provider payloads. Artifact
bodies remain in safe in-memory test fixtures; the serialized file stores only
kind, byte length, and digest where required.

When behavior changes, update the executable fixture, serialized fixture,
manifest hash, generated schema artifacts if the SDK shape changed, and both
validator suites in one change. A conformance JSON file that is merely packaged
but not consumed by executable tests is insufficient.

## Translations and attribution

Every manifest key must exist in the module-owned `translations/en.json` and
`translations/ru.json`. Translations describe the module and its environment
requirements; they do not contain HTML or JavaScript. Provider attribution is
declared in the manifest and projected through safe control DTOs.

## Validation commands

Run the focused package tests first, then the shared contract gates:

```console
uv run pytest --no-cov packages/modules/<module>/tests
uv run pytest --no-cov packages/module-sdk/tests
pnpm module-conformance:test
pnpm module-conformance:validate
uv run pytest tests/architecture/test_package_boundaries.py tests/test_wheel_isolation.py
uv run ruff format --check .
uv run ruff check .
uv run mypy
pnpm spec:validate
```

The full repository and production image gates remain required before merge.

## Review checklist

- The approved OpenSpec change covers the new capability or behavior.
- The module is one independent wheel with one public typed registration.
- `module.toml` declares exact capabilities, translations, attribution, and
  environment names without values.
- Core contains no concrete module import, identifier branch, or provider-specific
  persistence rule.
- The module owns and closes its transports; the root owns capability lifetime.
- SDK DTOs, errors, limits, URL boundaries, and redaction are tested adversarially.
- Executable and serialized conformance describe the same behavior.
- The host registration and any explicit acquisition selection are updated.
- Package, architecture, schema, documentation, and image checks pass.

## Out-of-process modules

Do not add RPC, a sidecar, service discovery, retries, distributed tracing, or a
separate deployment merely to make a module appear more independent. The current
in-process model is appropriate while modules are trusted, reviewed, released,
and scaled with Media Finder.

Propose an out-of-process contract only for an observed independent trust,
ownership, release, scaling, resource-isolation, or non-Python deployment need.
That proposal must define a versioned wire protocol, authentication, bounded
payloads, health, timeouts, compatibility, deployment, and failure semantics.
Until then, the static SDK boundary has lower ownership and operational cost.
