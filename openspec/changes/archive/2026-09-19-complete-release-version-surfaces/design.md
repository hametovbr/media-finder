## Context

See proposal.md for motivation. The archived `automated-stable-release` change
delivered the deterministic preparer, the trusted controller and the stable
publisher. Evidence for the defects this change fixes is concrete rather than
speculative: the v0.4.0 release commit `03947f1` changed 22 files, the automated
v0.5.0 candidate changed 21, and the difference is exactly
`apps/server/src/media_finder_server/control_gateway.py` and
`tests/core/acquisition/test_module_runtime_integration.py`. The running server
reports `build_version` from the gateway's default because
`apps/server/src/media_finder_server/runtime.py` never supplies it, so an
unnoticed omission is a user-visible wrong version rather than a cosmetic one.

## Goals / Non-Goals

**Goals:** make the release transformation's version-surface set complete and
self-checking, so an omission fails a required check instead of shipping; and make
the repository's own tests runnable on a prepared tree.

**Non-Goals:** changing how the server discovers its version at runtime, changing
the controller or publisher, adding a new component or service, and performing a
product release.

## Decisions

### 1. The surface set stays explicit, and a test keeps it honest

The preparer keeps one ordered map of version-derived surfaces. Rather than
trying to infer surfaces from Git at runtime, a repository test asserts that the
prepared tree changes exactly the declared surfaces, and a second assertion
requires every declared surface to carry the requested product version. The
declared map gains the server gateway default. A hand-maintained list plus a
failing coverage assertion is chosen over history-driven inference because the
preparer must stay deterministic and offline.

### 2. The server's reported version is a lockstep surface

`BackendControlGateway.build_version` keeps its default parameter, and the
preparer updates that literal, matching what the v0.4.0 release commit did. A new
test asserts the default equals the root `VERSION`, which is the assertion that
was missing.

*Alternative considered:* remove the literal and have the composition root derive
the version from installed distribution metadata. That eliminates drift by
construction, but it changes runtime behavior and adds a new failure mode when
metadata is unavailable; it is a separate product concern and is not required by
the approved requirement, so it is recorded here rather than implemented.

### 3. Tests derive the version they assert

`tests/core/acquisition/test_module_runtime_integration.py` currently hard-codes
the product version in two assertions. It will read the expected version from the
first-party composition's own manifests, which is the same source the runtime
uses, so a version bump cannot break it and the preparer never needs to edit a
test.

### 4. The preparer's tests do not depend on the live tree

`tests/test_prepare_release.py` builds fixtures with `git archive HEAD` of the
checkout it happens to run in, so twelve of its tests fail on any prepared tree.
Fixtures will instead be built from an explicitly requested base version, keeping
the test independent of the tree it runs in.

## Risks / Trade-offs

- A hand-maintained surface map can still miss a future surface → the coverage
  assertion fails the build instead of shipping, which is the intended trade.
- Changing the gateway literal touches production source → the value is already
  the product version and the new lockstep assertion proves it stays correct.
- Making the prepare-release tests version-agnostic could weaken their
  independence from the preparer's own logic → fixtures stay synthetic and fully
  specified rather than derived from the code under test.
