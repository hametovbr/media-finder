# Modular Media Systems: Architecture Research

> Status: non-normative research note. OpenSpec remains the source of truth for Media Finder architecture and behavior.
>
> Research date: 2026-08-15

## Research question

Which open-source media-management systems use a model similar to “a small core plus independently developed extension modules,” what has worked in those systems, and which failure modes should Media Finder avoid?

The comparison focuses on extension contracts, ownership of persistent state, module isolation, UI boundaries, packaging, compatibility, and the feasibility of replacing the current Python implementation later. It does not compare media-processing quality or feature breadth.

## Executive conclusion

No reviewed project is an exact match for Media Finder. The closest useful references are complementary rather than interchangeable:

- **FlexGet** is the strongest example of an application where plugins provide most behavior and compose into workflows.
- **Stash** is the closest self-hosted media organizer with a core-owned database, a public frontend API, metadata scrapers, and executable plugins.
- **Jellyfin** demonstrates mature typed extension categories, manifests, compatibility metadata, catalogs, and contributor templates.
- **MusicBrainz Picard** demonstrates explicit plugin API compatibility declarations and narrowly registered extension points.
- **beets**, **calibre**, and **Kodi** demonstrate both the reach and long-term cost of broad in-process plugin APIs.
- **Sonarr/Radarr** are useful negative comparators: they contain internal abstractions, but do not offer a narrow, stable third-party module SDK for replacing their core integrations.

The most appropriate direction for Media Finder is therefore:

> Not everything is a runtime plugin. Every replaceable capability is a module with a narrow, versioned contract, while business invariants and durable data remain core-owned.

For the current product stage, modules should be statically registered workspace packages, tested through one public conformance suite, and shipped in the same image. A runtime marketplace, hot loading, sandbox, dependency resolver, and cross-process protocol are not yet justified.

## Comparison matrix

| System | Extension model | Strongest lesson | Main warning for Media Finder |
|---|---|---|---|
| FlexGet | In-process Python plugins by phase, interface, category, and API version | A uniform registration model can make most features composable | Shared mutable entries and phase ordering create implicit coupling |
| Stash | Go core, GraphQL UI boundary, scrapers, raw/RPC plugins, UI extensions | Keep persistence in core and use serialized boundaries where independence matters | Broad plugin credentials, UI injection, and post-commit hooks enlarge the trust surface |
| Jellyfin | In-process .NET assemblies implementing specialized interfaces | Typed extension categories, stable IDs, manifests, catalogs, and templates improve ecosystem quality | Plugins are coupled to the server runtime and compatible package versions |
| beets | Python namespace plugins, metadata sources, import stages, events, commands | First-party and third-party extensions can use the same contributor path | Plugins receive rich core objects and can extend database/query semantics |
| Picard | Python hooks with priorities and declared API-version compatibility | Compatibility negotiation should be explicit and machine-readable | Hook ordering and in-process domain objects limit isolation |
| calibre | Many specialized Python plugin base classes and capabilities | Mature extension categories make supported use cases discoverable | A very broad SDK becomes a permanent compatibility and maintenance burden |
| Kodi | Repository-delivered add-ons, metadata scrapers, skins, services | Providers and UI packages can be independently distributed | Marketplace, runtime, and platform compatibility add substantial operational complexity |
| Sonarr/Radarr | Core-owned internal abstractions and integrations | Central ownership reduces unknown runtime code | Adding an integration requires knowledge of and changes to core internals |

## Detailed findings

### FlexGet

[FlexGet describes plugins as providing most of its functionality](https://flexget.com/Plugins). Plugin types include inputs, filters, outputs, metadata, modification, daemon, and command-line features. Its public plugin metadata includes a name, interfaces, category, and API version, and plugins can register task phases and priorities through the [plugin API](https://flexget.readthedocs.io/en/stable/api/flexget.plugin.html).

Strengths:

- One extension mechanism covers built-in and third-party behavior.
- Registration metadata makes discovery and compatibility checks possible.
- Configuration schemas remain close to plugin implementations.
- Inputs, filters, metadata enrichment, and outputs are naturally composable.
- The ecosystem proves that contributors can add metadata and download integrations without rebuilding the conceptual core.

Weaknesses:

- Plugins communicate through a mutable `Entry` whose fields are partly conventional and not guaranteed; the [Entry documentation](https://flexget.com/Entry) explicitly allows fields to appear or disappear depending on plugins and configuration.
- Correct behavior depends on phase and priority ordering.
- A plugin can look up and call another plugin, increasing hidden coupling.
- In-process Python plugins share the core runtime and failure domain.
- The architecture is optimized for repeatable YAML automation over transient candidates, not for a durable, human-curated catalog with immutable metadata revisions.

#### FlexGet versus Media Finder

FlexGet is primarily a rule-driven automation engine: it gathers candidate entries, transforms and filters them, then performs outputs on accepted entries. Media Finder is a catalog and acquisition control plane: it stores durable media identity and metadata revisions, presents explicit human choices, records acquisitions pinned to metadata, and exposes stable naming/NFO contracts to an external processor.

Consequently, Media Finder should adopt FlexGet’s uniform module registration and composability, but not its shared mutable entry as the central domain model. Core-owned immutable DTOs and explicit commands/results better fit Media Finder’s durable audit and identity requirements.

### Stash

Stash’s [architecture documentation](https://github.com/stashapp/stash/blob/develop/docs/ARCHITECTURE.md) describes a Go backend, SQLite persistence behind repository interfaces, a GraphQL API, a React frontend, metadata scrapers, jobs, and executable plugins. The default frontend is embedded in the application, while the API remains a distinct boundary.

Strengths:

- Persistence interfaces and SQLite implementations are core-owned.
- The frontend consumes a serialized API instead of database or repository objects.
- Metadata scrapers are distinguished from general-purpose plugins.
- Raw/RPC executable plugins demonstrate a path toward language-neutral extensions.
- A single deployable can still contain a separately developed frontend.

Weaknesses:

- External plugins may need powerful connection information or session credentials.
- JavaScript/CSS UI extensions increase CSP, supply-chain, and compatibility risk.
- Generic hooks such as post-create or post-update can recurse, interact, and become order-dependent.
- Generic process output and errors provide weaker contracts than typed operation-specific results.
- Post-commit hooks cannot participate safely in the transaction that caused the event.

Media Finder should copy Stash’s core-owned persistence and API-separated UI, but expose narrower, capability-specific operations than a general event or RPC execution surface.

### Jellyfin

Jellyfin distributes extensions through [plugin repositories and a catalog](https://jellyfin.org/docs/general/server/plugins/). Its [official plugin template](https://github.com/jellyfin/jellyfin-plugin-template) demonstrates stable plugin identifiers, configuration models, dependency injection, and specialized interfaces for metadata, authentication, scheduled tasks, resolvers, controllers, hosted services, and other extension categories.

Strengths:

- Specialized typed interfaces communicate intent better than a generic plugin callback.
- Stable IDs, manifests, versions, catalogs, and templates reduce contributor ambiguity.
- Capability categories make discovery and UI presentation possible.
- Official scaffolding establishes a repeatable module-development path.

Weaknesses:

- Plugins compile against Jellyfin packages and must match compatible server versions.
- Plugins can register services, background workers, controllers, configuration pages, and access powerful core managers; this is flexible but broad.
- Runtime install/update behavior introduces compatibility, recovery, and supply-chain responsibilities.
- All plugins are trusted in-process code sharing the server failure domain.

Media Finder should borrow typed categories, manifests, stable identifiers, compatibility ranges, and contributor templates. It should not expose the dependency-injection container, route registration, database managers, or background-service registration to ordinary modules.

### beets

beets plugins extend `BeetsPlugin` and can add commands, metadata sources, import stages, query types, media fields, and lifecycle listeners. The [plugin development guide](https://docs.beets.io/en/latest/dev/plugins/index.html) deliberately makes a plugin a normal Python namespace package, and the [plugin index](https://docs.beets.io/en/latest/plugins/index.html) treats metadata sources as a common extension case.

Strengths:

- Contributor setup is simple.
- First-party and third-party extensions follow the same mechanism.
- Dedicated metadata-source base classes improve consistency.
- Small plugins can be useful without infrastructure overhead.

Weaknesses:

- Plugins can receive library and domain objects directly through [events](https://docs.beets.io/en/latest/dev/plugins/events.html).
- Extensions may alter import stages, fields, query syntax, and database-adjacent behavior.
- The API is Python-specific and closely tied to internal domain representations.
- Event and stage order can become observable behavior.

The useful lesson is contributor ergonomics, not the breadth of access. Media Finder modules should be equally easy to add, but operate only on SDK DTOs and module-owned configuration.

### MusicBrainz Picard

Picard plugins declare their own version and supported plugin API versions and register focused processors, actions, formats, events, cover-art providers, or UI extensions. Its plugin documentation is published in the [Picard manual](https://picard-docs.musicbrainz.org/en/latest/extending/plugins.html).

Strengths:

- Compatibility negotiation is explicit rather than inferred.
- Extension points are named and registered deliberately.
- Priorities make ordering visible when ordering is unavoidable.

Weaknesses:

- The runtime remains Python-specific and in-process.
- Hooks still receive application-specific objects.
- Priorities resolve ordering mechanically but do not remove semantic coupling.

Media Finder manifests should similarly declare both module version and supported SDK/contract versions. Operations that should not compose by order must remain single-owner commands rather than prioritized hooks.

### calibre

calibre states that [almost all functionality is implemented as plugins](https://manual.calibre-ebook.com/creating_plugins.html). Its [plugin API](https://manual.calibre-ebook.com/plugins.html) defines many specialized classes for file types, metadata, conversion, catalogs, devices, UI actions, and preferences.

Strengths:

- Extension categories and capability fields are mature and discoverable.
- The architecture has supported a large ecosystem for many years.
- Packaging, platform support, minimum versions, priorities, and UI integration are first-class concepts.

Weaknesses:

- The SDK surface is very large and becomes a permanent compatibility commitment.
- Plugins can access GUI objects, database objects, files, threads, and other plugins.
- UI and backend extension APIs are tied to calibre’s Python/Qt runtime.
- Priority-based conflict handling can hide ambiguous ownership.

The principal lesson is subtraction: publish only extension points backed by a current use case and a second plausible implementation. Avoid a “complete platform” SDK before real consumers exist.

### Kodi

Kodi supports repository-delivered add-ons for sources, services, scripts, subtitles, metadata scrapers, and UI concerns; its extension categories are summarized in the [add-on development guide](https://kodi.wiki/view/Add-on_development). Metadata providers are independent scraper add-ons, and Kodi has moved from legacy XML scrapers to Python because modern provider APIs outgrew the older format, as noted in the [scraper documentation](https://kodi.wiki/view/Scrapers).

Strengths:

- Metadata providers and UI packages have independent distribution paths.
- Repository rules and packaging make ecosystem governance explicit.
- The migration away from an insufficient declarative scraper format is a useful reminder that provider integrations need real programming-language escape hatches.

Weaknesses:

- Runtime installation requires repository governance, compatibility checks, and security review.
- Add-ons are tied to Kodi’s platform APIs and Python runtime.
- Skins and UI extensions create a larger compatibility surface than data-provider modules.

Media Finder should keep provider contracts expressive enough for real APIs, but defer repository installation and marketplace governance until external demand exists.

### Sonarr and Radarr as negative comparators

[Sonarr](https://github.com/Sonarr/Sonarr) and [Radarr](https://github.com/Radarr/Radarr) contain internal abstractions for indexers, download clients, metadata, notifications, and other integrations. Those abstractions are effective for maintaining a centrally released product, but they are not a small, separately versioned third-party SDK with independent package conformance.

Strengths:

- Core maintainers control integration quality and release compatibility.
- There is no runtime marketplace or unknown-code loading path to operate.
- Internal abstractions can evolve together with the application.

Weaknesses:

- A contributor adding an integration must understand core internals and modify the main product.
- Provider-specific branches and assumptions can accumulate outside integration packages.
- Reuse outside the original runtime is difficult.

Media Finder should preserve static inclusion through repository changes for now, while making the repository contribution boundary a real public SDK rather than an internal convention.

### FileFlows

FileFlows is architecturally relevant as a visual processing engine whose functionality can be extended with [.NET plugins and JavaScript scripts](https://fileflows.com/docs). Its [plugin management documentation](https://fileflows.com/docs/webconsole/config/extensions/plugins) includes runtime download and automatic updates.

It is not used as a primary open-source architectural reference here because the currently published product, licensing tiers, and available repositories do not provide the same clearly auditable full-application open-source basis as the projects above. Its flow model is also aimed at file processing, whereas Media Finder explicitly leaves scanning, muxing, moving, and media processing to external processors.

The useful lesson is limited: if Media Finder later needs processor orchestration, a typed flow graph may be appropriate in that separate subsystem. It should not be introduced into catalog and acquisition core merely because the model is flexible.

## Cross-system findings

### Patterns that consistently work

1. **Specialized extension kinds beat a universal callback.** Metadata providers, release providers, download clients, and UI adapters have different operations, failure modes, and trust requirements.
2. **Core-owned persistence protects invariants.** Modules should return proposed data or effects; core should validate, transact, persist, and audit them.
3. **One path for first-party and contributor modules prevents privileged bypasses.** First-party modules must pass the same manifest and conformance rules expected of future external contributors.
4. **Compatibility must be declared.** Stable module identity, module version, SDK range, contract version, and capabilities should be machine-readable.
5. **Fixtures and conformance tests are part of the SDK.** A protocol definition alone does not demonstrate error safety, secret handling, locale behavior, retention, or artifact capabilities.
6. **A separately developed UI needs an HTTP contract, not backend imports.** This also provides the strongest seam for a future language rewrite.
7. **Static packaging is a valid modular architecture.** Independent code ownership and contracts do not require runtime installation.

### Recurring failure modes

1. **Shared mutable context objects.** They turn field names and execution order into an undocumented API.
2. **Broad core-object access.** Database sessions, ORM entities, service containers, framework request objects, and UI internals make modules impossible to isolate or port.
3. **Generic hooks and event buses.** They obscure ownership, transaction semantics, ordering, retries, and recursion.
4. **Unbounded SDK surfaces.** Every exposed internal object becomes a compatibility obligation.
5. **Runtime marketplaces too early.** Installation, signing, dependency resolution, upgrades, rollback, and untrusted-code handling become product features of their own.
6. **UI code injection.** Arbitrary module HTML, JavaScript, CSS, or route registration expands the security and compatibility boundary dramatically.
7. **Language-specific contracts as the only source of truth.** Python protocols alone do not support a later rewrite or an out-of-process implementation.
8. **Module-owned durable state in the core database.** This complicates migration, uninstall, rollback, and cross-language replacement.

## Recommended Media Finder boundaries

### Core responsibilities

Core should exclusively own:

- media identity, collections, and catalog invariants;
- normalized metadata schemas and immutable revision envelopes;
- user overrides and acquisition history;
- idempotency, transactions, persistence, and migration;
- secret resolution and redaction;
- module registration, lifecycle, timeouts, and error translation;
- execution of provider-supplied retention decisions;
- browser control and processor APIs;
- opaque-token lifecycle and bounded caches;
- module conformance tooling.

Modules must not receive database sessions, ORM entities, repositories, the dependency-injection container, FastAPI routers, templates, or mutable core domain objects.

### Module kinds justified now

#### Metadata provider

Examples: Manual, TMDB.

Typed operations:

- validate environment configuration;
- search;
- fetch by provider identity;
- normalize to a versioned core schema;
- provide attribution;
- compute provider-owned retention actions;
- provide safe export warnings.

Manual remains a provider because it supplies metadata through the same normalized boundary. Core still owns UUID allocation, duplicate detection, confirmation semantics, transactions, and revision creation.

#### Release provider

Example: Prowlarr.

Typed operations:

- validate environment configuration;
- search releases with bounded results;
- resolve an opaque selection into a short-lived acquisition artifact.

Prowlarr should be modeled as a release provider rather than a core-only special adapter once the new module architecture is adopted. Sensitive URLs, credentials, magnets, and torrent bytes remain inside the module/core trust boundary.

#### Download client

Example: qBittorrent.

Typed operations:

- validate environment configuration;
- list live destinations;
- submit only declared artifact forms;
- find an item by an exact correlation token.

#### UI module

Example: built-in Jinja/HTMX UI.

UI is a replaceable presentation module but has a different boundary from backend integration modules. It should depend only on the browser control contract and browser-security port. An external UI should use the same-origin `/api/control/v1` API. It must never access the module SDK, persistence, repositories, or integration instances.

### Capabilities that should remain core-owned for now

- Naming profiles and NFO export should remain core services until a second concrete implementation demonstrates a real variability axis.
- Maintenance scheduling remains core; providers own only retention decisions.
- Normalized metadata and acquisition schemas remain core contracts.
- No generic workflow engine or event bus should be introduced for current catalog and acquisition flows.

## Contract and packaging guidance

Canonical contracts should be language-neutral and serializable:

- JSON Schema or OpenAPI for DTO shapes;
- stable machine-readable error codes;
- explicit schema and contract versions;
- golden request/result fixtures;
- deterministic conformance cases.

The Python SDK should be a convenient binding over those contracts, not their sole definition. DTOs must not contain ORM entities, sessions, callbacks, framework responses, or Python-only runtime objects.

Each module manifest should declare at least:

```text
module_id
module_kind
module_version
sdk_version_range
contract_version
capabilities
environment_variables[]
attribution
```

Every environment declaration should include its exact name, whether it is required, whether it is secret, and a localizable description key. Core resolves values and passes only the validated in-memory configuration to the module.

A suitable monorepo shape is:

```text
packages/
  core/
  module-sdk/
  control-contracts/
  modules/
    metadata-manual/
    metadata-tmdb/
    release-prowlarr/
    download-qbittorrent/
  ui/
    builtin-ui/
```

Each module should be an independently buildable workspace package with its own manifest, fixtures, tests, and conformance invocation. All modules may still be installed into one production image through an immutable static registry.

## Failure and trust boundaries

For every module operation, core should:

- construct validated immutable input DTOs;
- enforce a timeout and cancellation policy;
- bound response counts and payload sizes;
- translate failures into stable safe codes;
- redact secrets and sensitive URLs;
- validate the returned DTO before using it;
- own database transactions and commits;
- prevent one module failure from skipping mandatory work for another record or module;
- close resources under explicit per-instance ownership.

In-process modules remain trusted code and share the process failure domain. This is acceptable for statically reviewed modules in one image. If genuinely independent, differently trusted, or differently implemented modules appear later, core can add an adapter such as `OutOfProcessJsonRpcModuleAdapter` without changing domain contracts. That adapter is a future option, not a current requirement.

## Architecture enforcement

Automated architecture tests should reject:

- module imports from core implementation packages, SQLAlchemy, persistence models, repositories, runtime composition, or UI packages;
- module-created tables in the core database;
- module registration of FastAPI routes, templates, JavaScript, or arbitrary background services;
- UI imports from core, persistence, integrations, or the module SDK;
- provider-specific branches or retention durations in core;
- first-party module construction that bypasses the public registry and SDK;
- generic mutable execution contexts;
- secrets, provider download URLs, magnets, or torrent bytes in public DTOs, persistence, diagnostics, or logs;
- conformance tests that inspect module internals instead of public behavior.

## Complexity intentionally deferred

The following components should not be built until an observed requirement justifies them:

- runtime module installation or hot reload;
- a module marketplace or repository protocol;
- code signing and trust levels;
- a dependency resolver for modules;
- plugin-owned database migrations;
- arbitrary event subscriptions;
- module-supplied routes or UI assets;
- a separate module host process;
- JSON-RPC, gRPC, or message-bus transport;
- independent module deployment or scaling.

Concrete triggers for reconsideration include a real third-party module maintained outside the repository, a module requiring a non-Python runtime, a security requirement to isolate provider code, independent operational ownership, or a demonstrated need to upgrade modules without releasing the application.

## Proposed decision statement for a future OpenSpec change

Media Finder should adopt a modular-monolith architecture in which core owns durable state and business invariants, while replaceable metadata, release-search, download-client, and presentation capabilities are implemented as statically packaged modules behind narrow versioned contracts. First-party modules use the same SDK, manifests, static registry, and conformance suite required of contributor modules. The browser UI communicates only through the versioned control API. Canonical DTOs and fixtures remain serializable and implementation-language neutral so an in-process Python binding can later be replaced or complemented without rewriting the domain contract.

This research note does not approve that change. The proposal, exact contracts, migration freedom, and package reorganization must be specified and accepted through OpenSpec before implementation.

