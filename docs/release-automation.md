# Automated stable release operator guide

This guide documents the approved target behavior and one-time setup for the
repository-scoped automation for a stable Media Finder release. The controller's
request and recovery integration is implemented in the current uncommitted
candidate on the checkpoint branch, but that work is not delivered or activated
and no live validation has been performed; the feature is not active or
operational, this guide is not evidence that a release can be run, and no
release can be run until delivery, activation and live validation have each
succeeded. An authorized repository writer will then submit one explicit product
version in GitHub Actions.
The trusted controller will prepare a release branch and pull request, wait for
the required checks, perform a normal protected squash merge, verify the
resulting `main` and `edge` state, and publish the stable GitHub Release and
GHCR tags through the existing release workflow.

The intended workflow will not deploy Media Finder to an operator's server. The
first real product release requires separate product-release authorization after
the automation and its live prerequisites have been verified. Until the trusted
workflow and live event path are validated, this feature remains inactive. The
main-only dispatch entry point is
`.github/workflows/prepare-release.yaml`. The file is present and invokes the
`--phase request` controller entry point, but the workflow has not been activated
and no live event path has been validated. Do not attempt a release.

## One-time setup

### Install the release App

Create or use a dedicated **private GitHub App** owned by `hametovbr` and
install it on **only** the `hametovbr/media-finder` repository. Do not install it
for all repositories or an organization. The App is an automation identity;
branch names, labels, PR text, and workflow inputs are not credentials.

Configure the repository permissions exactly as follows:

| Permission area | Access | Purpose |
| --- | --- | --- |
| Contents | Read and write | Create the release branch and commit the generated candidate |
| Pull requests | Read and write | Create, inspect, update, and close the generated PR |
| Actions | Read | Inspect trusted workflow runs and recovery evidence |
| Checks | Read | Verify the seven required check results |
| Metadata | Read | Identify the repository and installation scope |
| Administration | Read | Inspect repository settings, including main-branch protection |

Administration read is the only Administration access allowed. It is used for
repository settings inspection, including the authenticated main-branch
protection read. The App must not receive **Administration write**, **Workflows**,
**Checks write**, branch-protection bypass, approval impersonation, or any other
administrative authority. The controller uses normal protected merge behavior
and must never change rules or bypass required checks.

### Configure the repository credentials

In the repository's **Settings → Secrets and variables → Actions** page, add:

| Kind | Name | Value |
| --- | --- | --- |
| Repository variable | `RELEASE_APP_CLIENT_ID` | The App client ID |
| Repository secret | `RELEASE_APP_PRIVATE_KEY` | The App private key |

Keep the private key in the repository secret store. Never put it in a pull
request, candidate files, logs, notes, or recovery artifacts. The trusted
controller obtains short-lived, repository-scoped installation tokens and
renews them before expiry; tokens are not persisted.

The owner reports that the App was created and installed, these names are
configured, and the updated Administration read permission was added on
2026-09-16. This remains owner-reported setup information, not verified
evidence of installation acceptance, token issuance, exact effective
permissions, repository scope, a successful live protection read, or event
propagation. Before activation, the trusted workflow must verify all of those
facts: the installation must accept the updated grant; each issued token must
have exactly the approved permissions and repository scope, with forbidden
permissions rejected; and an authenticated read of main-branch protection must
succeed. Until those checks and the live event path succeed, the feature remains
inactive. Do not expose or read the private key while performing that
validation.

### Preserve the protection baseline

The supplied baseline screenshots report the following main-branch controls:

- pull requests are required;
- the seven verification contexts are required and must be current;
- conversations must be resolved;
- linear history is required;
- force-push, deletion, and bypass are disabled; and
- approvals, code-owner approval, and approval of the most recent push are
  already disabled.

The screenshots are owner-supplied baseline evidence, not a successful live
protection API read. The authenticated read required before activation, before
candidate exposure, and before each merge must match this baseline. Because
approvals are already disabled, an authenticated generated release PR needs no
human or AI approval per release. The automation itself and later changes to it
still go through the ordinary implementation review process. Do not add a
release-specific protection exception, change branch rules, grant GitHub bypass,
or weaken any existing gate. A protection change or newly required approval is a
stop condition.

## Run an activated release from phone Safari

Before starting, confirm that you are an authorized repository writer, the App
prerequisites have been validated, no different release version is active, and
the requested version is a new canonical stable SemVer greater than both the
current product version and the latest stable release. Do not use prerelease or
build metadata, shell syntax, or a moving tag as the input.

1. Open `github.com` in Safari and navigate to `hametovbr/media-finder`.
2. Open **Actions** and select the main-only `prepare-release.yaml` workflow.
3. Choose **Run workflow**, keep the branch set to `main`, and enter the
   explicit canonical version in the `version` field.
4. Submit the workflow once. Record the workflow URL and the operation/version
   shown in its summary.
5. Let the controller create its dedicated non-main branch and PR. Do not edit
   the generated branch or PR, add labels as authorization, approve it, or
   rerun it with a different version.
6. Wait for every required check and the protected squash merge. A valid
   generated release PR proceeds without a per-release human or AI review.
7. Confirm the final summary before treating the release as complete. It must
   identify the PR, head and base SHAs, merged SHA, release and workflow URLs,
   the immutable and moving tags, the image digest, and both supported Linux
   platforms.

The generated notes use English framing, identify the exact previous stable
release and included history, link commits and PRs, and include this exact
statement:

> `Automatically generated from repository history. Not editorially reviewed.`

Titles from other languages are retained through stable references and links;
they are not copied as English prose. The notes do not infer migration,
compatibility, or rollback safety. Use the [backup and upgrade procedure](operations.md#backup-before-every-upgrade)
for the general operational steps.

The seven required verification jobs are:

| Job | What it covers |
| --- | --- |
| `documentation` | English documentation, OpenSpec, and delivery-policy checks |
| `python` | Python/UI quality, type checks, wheel isolation, and generated assets |
| `unit` | Unit and core behavior suites |
| `integration` | Server and integration suites |
| `contract` | Architecture, module, serialized conformance, API, and schema checks |
| `browser` | Built-in UI browser checks and evidence |
| `image` | Production-image build and smoke test |

All seven results must be successful for the current candidate head and base.
Missing, skipped, cancelled, failed, stale, or untrusted evidence prevents
merge and publication. After the protected merge, `main` verification and
`edge` publication must belong to that exact merged SHA; an unrelated later
commit cannot satisfy the release gates.

## What the controller will do after activation

When the approved controller/workflow is delivered and activated, it will run
trusted release logic from `main` and keep candidate code away from write
credentials. It will record the requested version, previous stable tag,
original base, expected generated tree, prepared head, PR, merge, release, and
image identities. It will regenerate from captured inputs and refuse an
unexpected dependency, API, SDK, schema, generated-value, or other tree change.
History capture is bounded: when the complete previous-stable range cannot be
captured within that bound, the operation stops with an explicit bound error
instead of silently truncating the range it puts in the notes.

Installation tokens will be checked for App identity, installation, repository
scope, and permissions whenever they are issued. Before each authenticated API
batch, including polling, the controller will renew a token with fewer than five
minutes remaining. A failed renewal will stop authenticated actions; an expired
mutation will be reconciled from GitHub state before any retry.

After all seven current checks pass, the controller will use the expected head
SHA for a normal protected squash merge. It will never approve its own PR,
resolve discussions, force-push, use an administrative merge, change
protection, or auto-merge ordinary PRs.

## Timeout and same-version resume

The approved controller will use bounded polling and an overall deadline below
the hosted job limit. A timeout will leave a resumable operation state and report
the completed boundary. Once the workflow is activated, resume by running the
trusted workflow again with the **same canonical version**. The controller will
reconcile the existing branch, PR, checks, draft release, merge, and publication
state before every new mutation; it will not blindly repeat an uncertain
request or create duplicate state.

These safeguards apply only when the run executes the workflow revision that
contains this automation. A rerun of a historical pre-change workflow keeps its
old controller and publisher and must not be used to repair a new publication.
Use the current controller's same-version resume path and the current
publisher's immutable-state guard. Historical runs and publications that did
not already use this controller are not retroactively protected by these
safeguards. This guide makes no claim of retroactive migration for older runs or
publications.

An Actions read does not rerun the publisher automatically. If the current
publisher run fails, fix the cause and republish. When the failure is in the
publisher itself, the release commit still carries the older publisher, so a rerun
of that release event would repeat the same failure: use the workflow's manual
`Publish stable container` entry point and give it the existing stable release tag.
That entry point resolves the tag, requires a published non-prerelease release
whose commit carries the version in its `VERSION` file and its own seven
successful verification contexts, publishes the source at that release commit
using the trusted publisher from `main`, and uploads the same publication
evidence. It never moves the tag, changes its target, or rebuilds an image that
already exists. Then resume the controller with the same canonical version so it
reconciles the resulting publication evidence. Do not use a historical pre-change
publisher run or create a duplicate published Release to replace an uncertain
result.

A resume is allowed only while the immutable recovery evidence is available
and within its actual retention period. Preparation and later checkpoints bind
together the repository and App installation IDs, operation and attempt IDs,
trusted workflow revision and run attempt, artifact ID and digest, base/head/
merged SHAs, expected tree, and captured release-note inputs. GitHub workflow
provenance and verified digests establish trust; a PR-provided artifact name,
branch, label, or self-declared hash does not.

Preparation and checkpoint artifacts request **90-day retention**, bounded by
repository policy. The workflow reports the actual expiry. If evidence is
missing, deleted, expired, altered, forged, ambiguous, or from an untrusted
run, recovery stops. Do not rebuild expectations from mutable PR content.

If `main` advances before an otherwise authentic candidate merges, the run
that discovers this first reconciles whether the merge already happened. If it
did not, that run records the terminal stale attempt, closes the PR while
retaining its branch and evidence, and stops with `base_changed`; it does not
create the replacement itself. Re-dispatch the same canonical version from the
trusted workflow. The resumed operation prepares the next bounded attempt (a
new branch and PR from current `main`), regenerates the notes from that base,
and requires all seven checks for the replacement head/base; it never
force-pushes or overwrites manual edits. There are at most **three candidate
attempts per repository and version, including across reruns**. When the budget
is exhausted, the operation stops with `base_changed_repeatedly`; a rerun
cannot reset the count.

## Stop conditions

Stop and preserve the reported state when any of these conditions occurs:

| Condition | Required behavior |
| --- | --- |
| Missing credentials, unexpected App/repository scope, actor, branch, label, input, or workflow provenance | Stop before side effects; names and labels do not authorize a retry |
| Extra candidate edits or altered generated/conformance values | Refuse merge without overwriting the PR |
| Any required check is missing, unsuccessful, stale, skipped, cancelled, or untrusted | Do not merge or publish |
| Unresolved discussion, changed protection, or newly required approval | Stop; do not resolve, bypass, or change GitHub rules |
| Ambiguous mutation result or expired token | Reconcile resulting state before any retry |
| Missing, tampered, forged, deleted, expired, or ambiguous recovery evidence | Stop; do not reconstruct inputs from the PR |
| Existing tag, release, or image conflicts, or image publication is partial or unverifiable | Stop and report the completed boundary; never replace immutable or newer state |
| First real product release lacks separate product-release authorization | Keep activation blocked and obtain product-release authorization from the release owner |

If the App schema, repository settings, workflow inputs, or a summary differs
from this guide, inspect the workflow failure and verify the configuration with
the repository maintainer before changing permissions or retrying.

## Disable and roll back the automation

Rolling back the automation means stopping its ability to start new release
operations while retaining the audit trail:

1. Disable the `prepare-release.yaml` workflow dispatch entry point.
2. Revoke the dedicated App installation or its credentials, and rotate/remove
   the repository variable and secret as directed by the credential owner.
3. Retain existing branches, PRs, workflow runs, recovery artifacts, releases,
   tags, and evidence for investigation and history. Do not rewrite or delete
   immutable release state.
4. Resume release preparation through the existing manual reviewed process
   under the unchanged branch-protection rules.

This procedure does not automatically roll back a published GitHub Release or
container. For an already deployed image, use the [normal image and data
rollback procedure](operations.md#rollback); no server deployment or rollback
is initiated by this automation.
