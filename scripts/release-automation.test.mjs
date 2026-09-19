import assert from "node:assert/strict";
import crypto from "node:crypto";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  DEFAULT_OPERATION_DEADLINE_MS,
  GitHubAppAuthenticator,
  GitHubRestApi,
  ReleaseAutomationError,
  GITHUB_ACTIONS_APP_ID,
  REQUIRED_CHECK_CONTEXTS,
  assertReleaseMetadata,
  assertApprovedBranchProtection,
  assertPreparationArtifact,
  buildPreparationEvidence,
  buildStructuredEvidence,
  formatWorkflowSummary,
  canonicalJson,
  checkMainPublication,
  compareStableVersions,
  createActionsArtifactStore,
  evaluateRequiredChecks,
  readLatestStable,
  runReleaseAutomation,
  sanitizeCredentialEnvironment,
  sha256,
  validateDispatchContext,
  validatePublicationEvidence,
  validateRequestedVersion,
  waitForPublication,
} from "./release-automation.mjs";

const SHA = "a".repeat(40);
const DIGEST = "b".repeat(64);
const TOKEN_PERMISSIONS = {
  actions: "read",
  administration: "read",
  checks: "read",
  contents: "write",
  metadata: "read",
  pull_requests: "write",
};
const PRIVATE_KEY = crypto
  .generateKeyPairSync("rsa", { modulusLength: 2048 })
  .privateKey.export({ format: "pem", type: "pkcs1" });
const REPOSITORY_ID = 1334630722;
const CI_WORKFLOW_PATH = ".github/workflows/ci.yaml";
const RELEASE_WORKFLOW_PATH = ".github/workflows/release.yaml";
const DETERMINISTIC_PREPARATION_OPERATION_ID = `release-${sha256(`owner/media-finder\u00000.5.0\u000077`).slice(0, 20)}`;

function response(status, value) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    async json() {
      return value;
    },
    async text() {
      return JSON.stringify(value);
    },
  };
}

function authFixture(overrides = {}) {
  const { tokenPermissions = TOKEN_PERMISSIONS, ...authOverrides } = overrides;
  const calls = [];
  const app = {
    id: 123,
    client_id: "Iv1.fixture",
    slug: "media-finder-release",
  };
  const installation = {
    id: 456,
    app_id: 123,
    repository_selection: "selected",
  };
  const token = {
    token: "fixture-token",
    expires_at: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
    permissions: tokenPermissions,
  };
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).endsWith("/app")) return response(200, app);
    if (String(url).endsWith("/repos/owner/media-finder/installation")) {
      return response(200, installation);
    }
    if (String(url).endsWith("/app/installations/456/access_tokens")) {
      return response(201, token);
    }
    if (String(url).endsWith("/installation/repositories")) {
      return response(200, { repositories: [{ id: 1334630722, full_name: "owner/media-finder" }] });
    }
    return response(404, { message: "not found" });
  };
  return {
    calls,
    authenticator: new GitHubAppAuthenticator({
      fetchImpl,
      appId: "Iv1.fixture",
      repository: "owner/media-finder",
      privateKey: PRIVATE_KEY,
      now: () => Date.now(),
      ...authOverrides,
    }),
  };
}

function protectionFixture(overrides = {}) {
  const contexts = [
    "verification / documentation",
    "verification / python",
    "verification / unit",
    "verification / integration",
    "verification / contract",
    "verification / browser",
    "verification / image",
  ];
  return {
    required_status_checks: {
      strict: true,
      contexts,
      checks: contexts.map((context) => ({ context, app_id: GITHUB_ACTIONS_APP_ID })),
    },
    enforce_admins: { enabled: true },
    required_pull_request_reviews: {
      required_approving_review_count: 0,
      require_code_owner_reviews: false,
      require_last_push_approval: false,
      bypass_pull_request_allowances: { users: [], teams: [], apps: [] },
    },
    required_linear_history: { enabled: true },
    allow_force_pushes: { enabled: false },
    allow_deletions: { enabled: false },
    required_conversation_resolution: { enabled: true },
    ...overrides,
  };
}

function protectionWithoutBypassAllowance() {
  const value = protectionFixture();
  delete value.required_pull_request_reviews.bypass_pull_request_allowances;
  return value;
}

function evidence(overrides = {}) {
  return buildPreparationEvidence({
    repository: "owner/media-finder",
    repositoryId: 1334630722,
    appId: 123,
    installationId: 456,
    operationId: "release-op-1",
    attempt: 1,
    trustedControllerSha: SHA,
    originRunId: 77,
    originRunAttempt: 1,
    baseSha: SHA,
    previousStableTag: "v0.4.0",
    previousStableSha: SHA,
    version: "0.5.0",
    notesInputSnapshot: {
      throughSha: SHA,
      commits: [{ sha: SHA, url: "https://github.com/owner/media-finder/commit/" + SHA }],
    },
    candidateFiles: [{ path: "VERSION", mode: "100644", content: "0.5.0\n" }],
    expectedTree: {
      VERSION: { mode: "100644", sha256: sha256("0.5.0\n") },
    },
    candidateTreeSha256: preparationWorkingTreeDigest([{ path: "VERSION", mode: "100644", content: "0.5.0\n" }]),
    preparedCommitSha: "e".repeat(40),
    preparedTreeSha: "f".repeat(40),
    ...overrides,
  });
}

function executableEvidence({ pullRequest = false } = {}) {
  const value = evidence();
  if (pullRequest) {
    value.prNumber = 12;
    value.prHeadSha = value.preparedCommitSha;
    value.prBaseSha = SHA;
  }
  delete value.contentDigest;
  value.contentDigest = sha256(canonicalJson(value));
  value.artifact = {
    id: 901,
    digest: DIGEST,
    name: "release-op-1-preparation-attempt-1",
    expiresAt: new Date(Date.now() + 3600000).toISOString(),
    retentionDaysRequested: 90,
    workflowRunId: 77,
  };
  return value;
}

// Test double for the credential-free regeneration boundary. It replaces both
// the clean-base checkout factory and the preparer process while preserving the
// controller's comparison contract: the reproduced tree must equal the recorded
// immutable tree, otherwise the controller must refuse to merge.
function regenerationPreparer(state, { calls, alter, onCheckout } = {}) {
  return {
    async createCheckout({ baseSha, sourceCwd }) {
      calls?.push(["checkout", baseSha, sourceCwd]);
      const root = await fsp.mkdtemp(path.join(os.tmpdir(), "release-regeneration-fixture-"));
      onCheckout?.(root);
      return {
        root,
        async cleanup() {
          await fsp.rm(root, { recursive: true, force: true });
        },
      };
    },
    async prepare({ root, version, snapshot }) {
      const files = alter ? alter(state.candidateFiles) : state.candidateFiles;
      calls?.push(["regenerate", root, version]);
      for (const file of files) {
        const target = path.join(root, file.path);
        await fsp.mkdir(path.dirname(target), { recursive: true });
        await fsp.writeFile(target, file.content, "utf8");
      }
      return {
        schema_version: 1,
        version: state.version,
        base_commit: state.baseSha,
        previous_stable_tag: state.previousStableTag,
        previous_stable_sha: state.previousStableSha,
        snapshot_sha256: sha256(`${canonicalJson(snapshot)}\n`),
        base_tree_sha256: state.expectedTree.digest,
        candidate_tree_sha256: alter ? preparationWorkingTreeDigest(files) : state.candidateTreeSha256,
        notes_path: state.notesPath ?? files[0].path,
        changed_files: files.map((file) => file.path),
        expected_tree: Object.fromEntries(files.map((file) => [file.path, { mode: file.mode, sha256: sha256(file.content) }])),
      };
    },
  };
}

function executionFixture({ state, calls, protection, protectionError, pullRequestUserType, pullRequestRef, repositoryOwnerType = "User", mergeError, pullRequestPatch, listPullRequestsResults, createPullRequestError, preparer } = {}) {
  const contexts = protectionFixture().required_status_checks.contexts;
  const api = {
    async getCollaboratorPermission(...args) {
      calls.push(["actor", ...args]);
      return { permission: "push" };
    },
    async getArtifact(...args) {
      calls.push(["artifact", ...args]);
      return {
        id: 901,
        name: "release-op-1-preparation-attempt-1",
        digest: `sha256:${DIGEST}`,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        workflow_run: {
          id: 77,
          repository_id: REPOSITORY_ID,
          head_repository_id: REPOSITORY_ID,
          head_sha: SHA,
        },
      };
    },
    async getWorkflowRunAttempt(...args) {
      calls.push(["origin-run", ...args]);
      return {
        id: 77,
        run_attempt: args[1],
        status: "completed",
        conclusion: "success",
        event: "workflow_dispatch",
        path: "owner/media-finder/.github/workflows/prepare-release.yaml@main",
        head_sha: SHA,
        head_branch: "main",
        actor: { login: "maintainer", type: "User" },
        repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
        head_repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
        repository_id: REPOSITORY_ID,
        head_repository_id: REPOSITORY_ID,
      };
    },
    async listPullRequests(...args) {
      calls.push(["pulls", ...args]);
      if (listPullRequestsResults !== undefined) {
        const next = listPullRequestsResults.shift();
        return next ?? [];
      }
      return [];
    },
    async getRepository(...args) {
      calls.push(["repository", ...args]);
      return {
        id: REPOSITORY_ID,
        full_name: "owner/media-finder",
        owner: { type: repositoryOwnerType, login: "owner" },
      };
    },
    async getPullRequest(...args) {
      calls.push(["pr", ...args]);
      const pullRequest = {
        number: 12,
        state: "open",
        head: {
          ref: pullRequestRef ?? "release-op-1-v0.5.0-attempt-1",
          sha: state.preparedCommitSha,
          repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
        },
        base: {
          ref: "main",
          sha: state.baseSha,
          repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
        },
        user: { login: "media-finder-release[bot]", type: pullRequestUserType ?? "Bot" },
      };
      return pullRequestPatch ? pullRequestPatch(pullRequest) : pullRequest;
    },
    async listReviewThreads(...args) {
      calls.push(["threads", ...args]);
      return [];
    },
    async listReviewRequests(...args) {
      calls.push(["requests", ...args]);
      return { users: [], teams: [] };
    },
    async listReviews(...args) {
      calls.push(["reviews", ...args]);
      return [];
    },
    async getCheckRuns(...args) {
      calls.push(["checks", ...args]);
      const run = restWorkflowRun({ id: 700, runAttempt: 1, headSha: state.preparedCommitSha, baseSha: state.baseSha });
      return {
        check_runs: restCheckRuns(run),
      };
    },
    async getWorkflowRuns(input) {
      calls.push(["runs", input]);
      if (input.event === "pull_request") {
        const run = restWorkflowRun({ id: 700, runAttempt: 1, headSha: state.preparedCommitSha, baseSha: state.baseSha });
        return {
          total_count: 1,
          workflow_runs: [run],
        };
      }
      return { workflow_runs: [] };
    },
    async getWorkflowRunJobs(...args) {
      calls.push(["jobs", ...args]);
      const run = restWorkflowRun({ id: 700, runAttempt: args[1], headSha: state.preparedCommitSha, baseSha: state.baseSha });
      return { total_count: 7, jobs: restJobs(run) };
    },
    async listRunArtifacts(...args) {
      calls.push(["run-artifacts", ...args]);
      return { total_count: 0, artifacts: [] };
    },
    async getBranchProtection(...args) {
      calls.push(["protection", ...args]);
      if (protectionError) throw protectionError;
      return protection;
    },
    async getRef(...args) {
      calls.push(["ref", ...args]);
      if (args[0] === "heads/main") return { object: { sha: state.baseSha } };
      return { object: { sha: state.preparedCommitSha } };
    },
    async createPullRequest(...args) {
      calls.push(["createPullRequest", ...args]);
      if (createPullRequestError) throw createPullRequestError;
      return { number: 12 };
    },
    async getCommit(shaValue) {
      calls.push(["commit", shaValue]);
      assert.equal(shaValue, "e".repeat(40));
      return { tree: { sha: "f".repeat(40) }, parents: [{ sha: SHA }] };
    },
    async getTree(shaValue) {
      calls.push(["tree", shaValue]);
      assert.equal(shaValue, "f".repeat(40));
      return {
        truncated: false,
        tree: [{ path: "VERSION", mode: "100644", type: "blob", sha: sha256("0.5.0\n") }],
      };
    },
    async getBlob(shaValue) {
      calls.push(["blob", shaValue]);
      assert.equal(shaValue, sha256("0.5.0\n"));
      return { encoding: "base64", content: Buffer.from("0.5.0\n").toString("base64") };
    },
    async mergePullRequest(...args) {
      calls.push(["merge", ...args]);
      if (mergeError) throw mergeError;
      return { merged: true, sha: SHA, merge_commit_sha: SHA };
    },
  };
  return {
    api,
    auth: {
      current: {
        identity: {
          appId: 123,
          appSlug: "media-finder-release",
          installationId: 456,
          repository: "owner/media-finder",
          repositoryId: REPOSITORY_ID,
        },
      },
      async ensureToken() {},
    },
    artifacts: { async read() { return state; } },
    preparer: preparer ?? regenerationPreparer(state),
    context: {
      eventName: "workflow_dispatch",
      ref: "refs/heads/main",
      repository: "owner/media-finder",
      actor: "maintainer",
      sha: SHA,
      runId: 77,
      runAttempt: 1,
    },
  };
}

test("dispatch validation only accepts trusted workflow_dispatch on main", () => {
  assert.deepEqual(
    validateDispatchContext(
      {
        eventName: "workflow_dispatch",
        ref: "refs/heads/main",
        repository: "owner/media-finder",
        actor: "maintainer",
        sha: SHA,
        runId: 77,
        runAttempt: 1,
      },
      { repository: "owner/media-finder", allowedActors: ["maintainer"] },
    ).actor,
    "maintainer",
  );

  for (const context of [
    { eventName: "push", ref: "refs/heads/main", repository: "owner/media-finder", actor: "maintainer", sha: SHA, runId: 77, runAttempt: 1 },
    { eventName: "workflow_dispatch", ref: "refs/heads/release/v0.5.0", repository: "owner/media-finder", actor: "maintainer", sha: SHA, runId: 77, runAttempt: 1 },
    { eventName: "workflow_dispatch", ref: "refs/heads/main", repository: "evil/repo", actor: "maintainer", sha: SHA, runId: 77, runAttempt: 1 },
    { eventName: "workflow_dispatch", ref: "refs/heads/main", repository: "owner/media-finder", actor: "stranger", sha: SHA, runId: 77, runAttempt: 1 },
  ]) {
    assert.throws(
      () => validateDispatchContext(context, { repository: "owner/media-finder", allowedActors: ["maintainer"] }),
      ReleaseAutomationError,
    );
  }
});

test("execute and resume validate dispatch before reading recovery state", async () => {
  const state = executableEvidence();
  for (const phase of ["execute", "resume"]) {
    const calls = [];
    const fixture = executionFixture({ state, calls, protection: protectionFixture() });
    await assert.rejects(
      () => runReleaseAutomation({
        phase,
        ...fixture,
        context: { ...fixture.context, eventName: "push" },
        input: { state },
        config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
        clock: { now: () => Date.now(), sleep: async () => {} },
      }),
      (error) => error instanceof ReleaseAutomationError && error.code === "untrusted_trigger",
    );
    assert.deepEqual(calls, []);
  }
});

test("version validation rejects shell syntax, metadata, and non-increasing versions", () => {
  assert.equal(validateRequestedVersion("0.5.0", { currentVersion: "0.4.0", latestStableVersion: "0.4.0" }).text, "0.5.0");
  for (const value of ["0.5.0-rc.1", "0.5.0+build.1", "0.05.0", "0.5.0;rm -rf /", "0.4.0", "0.3.9"]) {
    assert.throws(
      () => validateRequestedVersion(value, { currentVersion: "0.4.0", latestStableVersion: "0.4.0" }),
      ReleaseAutomationError,
    );
  }
});

test("preparation evidence has bounded immutable identity and rejects secrets", () => {
  const valid = evidence();
  assert.equal(valid.schemaVersion, 1);
  assert.equal(valid.contentDigest.length, 64);
  assert.doesNotThrow(() => assertPreparationArtifact(valid, {
    repository: "owner/media-finder",
    trustedControllerSha: SHA,
    originRunId: 77,
    originRunAttempt: 1,
    version: "0.5.0",
    now: Date.now(),
  }));
  assert.doesNotThrow(() => assertPreparationArtifact({
    ...valid,
    artifact: {
      id: 901,
      digest: DIGEST,
      name: "release-op-1-preparation-attempt-1",
      expiresAt: new Date(Date.now() + 3600000).toISOString(),
      retentionDaysRequested: 90,
      workflowRunId: 77,
    },
  }, {
    repository: "owner/media-finder",
    trustedControllerSha: SHA,
    originRunId: 77,
    originRunAttempt: 1,
    version: "0.5.0",
    now: Date.now(),
  }));

  for (const altered of [
    { ...valid, repository: "evil/repo" },
    { ...valid, trustedControllerSha: "c".repeat(40) },
    { ...valid, version: "0.6.0" },
    { ...valid, notesInputSnapshot: { ...valid.notesInputSnapshot, token: "do-not-persist" } },
  ]) {
    assert.throws(
      () => assertPreparationArtifact(altered, {
        repository: "owner/media-finder",
        trustedControllerSha: SHA,
        originRunId: 77,
        originRunAttempt: 1,
        version: "0.5.0",
        now: Date.now(),
      }),
      ReleaseAutomationError,
    );
  }
});

test("credential-free regeneration removes write credentials and runtime tokens", () => {
  const clean = sanitizeCredentialEnvironment({
    PATH: "/usr/bin",
    GITHUB_TOKEN: "token",
    GH_TOKEN: "token",
    RELEASE_APP_PRIVATE_KEY: "private",
    ACTIONS_RUNTIME_TOKEN: "runtime",
    NODE_AUTH_TOKEN: "npm",
    SAFE_INPUT: "kept",
  });
  assert.equal(clean.SAFE_INPUT, "kept");
  for (const key of ["GITHUB_TOKEN", "GH_TOKEN", "RELEASE_APP_PRIVATE_KEY", "ACTIONS_RUNTIME_TOKEN", "NODE_AUTH_TOKEN"]) {
    assert.equal(clean[key], undefined, key);
  }
});

test("App authentication discovers installation, scopes token, and renews before five minutes", async () => {
  let now = Date.now();
  const fixture = authFixture({ now: () => now });
  const first = await fixture.authenticator.ensureToken();
  assert.equal(first.token, "fixture-token");
  assert.equal(fixture.calls.length, 4);
  assert.equal(fixture.calls[0].init.headers.Authorization.startsWith("Bearer "), true);
  assert.equal(fixture.calls[1].init.headers.Authorization.startsWith("Bearer "), true);
  assert.equal(fixture.calls[2].init.headers.Authorization.startsWith("Bearer "), true);
  assert.equal(fixture.calls[3].init.headers.Authorization.startsWith("Bearer "), true);
  const requested = JSON.parse(fixture.calls[2].init.body);
  assert.deepEqual(requested, {
    repositories: ["media-finder"],
    permissions: {
      actions: "read",
      checks: "read",
      contents: "write",
      metadata: "read",
      pull_requests: "write",
      administration: "read",
    },
  });

  now += 56 * 60 * 1000;
  const second = await fixture.authenticator.ensureToken();
  assert.equal(second.token, "fixture-token");
  assert.equal(fixture.calls.length, 8);
});

test("App authentication fails closed for unexpected repository scope or permissions", async () => {
  const fixture = authFixture({ privateKey: PRIVATE_KEY });
  fixture.authenticator.fetchImpl = async () => response(200, {
    id: 123,
    client_id: "Iv1.fixture",
  });
  await assert.rejects(() => fixture.authenticator.ensureToken(), ReleaseAutomationError);

  const bad = authFixture({ privateKey: PRIVATE_KEY });
  bad.authenticator.fetchImpl = async (url) => {
    if (String(url).endsWith("/app")) return response(200, { id: 123, client_id: "Iv1.fixture" });
    if (String(url).endsWith("/repos/owner/media-finder/installation")) {
      return response(200, { id: 456, app_id: 123, repository_selection: "selected" });
    }
    if (String(url).endsWith("/app/installations/456/access_tokens")) {
      return response(201, {
        token: "fixture-token",
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        permissions: { contents: "write", pull_requests: "write", metadata: "read", actions: "read", checks: "read", administration: "read" },
      });
    }
    if (String(url).endsWith("/installation/repositories")) {
      return response(200, { repositories: [{ id: 1, full_name: "evil/repo" }] });
    }
    return response(500, { message: "unexpected" });
  };
  await assert.rejects(() => bad.authenticator.ensureToken(), ReleaseAutomationError);
});

test("App authentication rejects missing, writable, or unexpected Administration permission", async () => {
  for (const permissions of [
    { ...TOKEN_PERMISSIONS, administration: "write" },
    Object.fromEntries(Object.entries(TOKEN_PERMISSIONS).filter(([name]) => name !== "administration")),
    { ...TOKEN_PERMISSIONS, repository_administration: "read" },
  ]) {
    const fixture = authFixture({ tokenPermissions: permissions });
    await assert.rejects(
      () => fixture.authenticator.ensureToken(),
      (error) => error instanceof ReleaseAutomationError && error.code === "token_scope_mismatch",
    );
  }
});

test("expired mutation is surfaced without blind retry", async () => {
  const fixture = authFixture({ privateKey: PRIVATE_KEY });
  fixture.authenticator.fetchImpl = async (url, init = {}) => {
    if (String(url).endsWith("/app")) return response(200, { id: 123, client_id: "Iv1.fixture", slug: "media-finder-release" });
    if (String(url).endsWith("/repos/owner/media-finder/installation")) {
      return response(200, { id: 456, app_id: 123, repository: { id: 1334630722, full_name: "owner/media-finder" } });
    }
    if (String(url).endsWith("/app/installations/456/access_tokens")) {
      return response(201, {
        token: "fixture-token",
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        permissions: { contents: "write", pull_requests: "write", metadata: "read", actions: "read", checks: "read", administration: "read" },
      });
    }
    if (String(url).endsWith("/installation/repositories")) {
      return response(200, { repositories: [{ id: 1334630722, full_name: "owner/media-finder" }] });
    }
    if (init.method === "POST") return response(401, { message: "expired" });
    return response(200, {});
  };
  await fixture.authenticator.ensureToken();
  await assert.rejects(
    () => fixture.authenticator.request("POST", "/repos/owner/media-finder/git/refs", { ref: "refs/heads/x", sha: SHA }),
    (error) => error instanceof ReleaseAutomationError && error.code === "token_expired",
  );
});

test("branch protection validates the approved nested REST baseline", () => {
  assert.doesNotThrow(() => assertApprovedBranchProtection(protectionFixture()));

  const baseline = protectionFixture();
  const altered = [
    { required_status_checks: { ...baseline.required_status_checks, strict: false } },
    { required_status_checks: { ...baseline.required_status_checks, checks: [{ context: "unexpected", app_id: GITHUB_ACTIONS_APP_ID }] } },
    { required_status_checks: { ...baseline.required_status_checks, checks: baseline.required_status_checks.checks.map((check) => ({ ...check, app_id: null })) } },
    { enforce_admins: { enabled: false } },
    { required_pull_request_reviews: { ...baseline.required_pull_request_reviews, required_approving_review_count: 1 } },
    { required_pull_request_reviews: { ...baseline.required_pull_request_reviews, require_code_owner_reviews: true } },
    { required_pull_request_reviews: { ...baseline.required_pull_request_reviews, require_last_push_approval: true } },
    { required_linear_history: { enabled: false } },
    { allow_force_pushes: { enabled: true } },
    { allow_deletions: { enabled: true } },
    { required_conversation_resolution: { enabled: false } },
    { required_pull_request_reviews: { ...baseline.required_pull_request_reviews, bypass_pull_request_allowances: { users: ["maintainer"], teams: [], apps: [] } } },
  ];
  for (const change of altered) {
    assert.throws(() => assertApprovedBranchProtection({ ...baseline, ...change }), ReleaseAutomationError);
  }

  for (const malformed of [
    {},
    { required_status_checks: null },
    { ...baseline, enforce_admins: true },
    { ...baseline, required_linear_history: { enabled: "true" } },
    { ...baseline, required_pull_request_reviews: { required_approving_review_count: 0 } },
  ]) {
    assert.throws(() => assertApprovedBranchProtection(malformed), ReleaseAutomationError);
  }
});

test("protection denial blocks candidate exposure before any branch mutation", async () => {
  const calls = [];
  const state = executableEvidence();
  const fixture = executionFixture({
    state,
    calls,
    protectionError: new ReleaseAutomationError("github_api_error", "Forbidden.", { status: 403 }),
  });
  await assert.rejects(
    () => runReleaseAutomation({
      phase: "execute",
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
      clock: { now: () => Date.now(), sleep: async () => {} },
    }),
    (error) => error instanceof ReleaseAutomationError && error.code === "github_api_error",
  );
  assert.deepEqual(calls.map(([name]) => name), ["actor", "origin-run", "actor", "artifact", "pulls", "runs", "repository", "protection"]);
});

test("protection drift blocks the squash mutation after candidate checks", async () => {
  const calls = [];
  const state = executableEvidence({ pullRequest: true });
  const fixture = executionFixture({
    state,
    calls,
    protection: protectionFixture({ required_linear_history: { enabled: false } }),
  });
  await assert.rejects(
    () => runReleaseAutomation({
      phase: "execute",
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
      clock: { now: () => Date.now(), sleep: async () => {} },
    }),
    (error) => error instanceof ReleaseAutomationError && error.code === "protection_changed",
  );
  assert.deepEqual(calls.map(([name]) => name), [
    "actor",
    "origin-run",
    "actor",
    "artifact",
    "pulls",
    "commit",
    "commit",
    "tree",
    "blob",
    "pr",
    "threads",
    "requests",
    "reviews",
    "checks",
    "runs",
    "jobs",
    "ref",
    "pr",
    "threads",
    "requests",
    "reviews",
    "repository",
    "protection",
  ].toSpliced(5, 0, "runs"));
  assert.equal(calls.some(([name]) => name === "merge"), false);
});

test("omitted bypass allowance follows authenticated repository owner semantics", async () => {
  const cases = [
    { ownerType: "User", protection: protectionWithoutBypassAllowance(), expectedCode: "fixture_stop" },
    { ownerType: "Organization", protection: protectionWithoutBypassAllowance(), expectedCode: "protection_malformed" },
    { ownerType: "Unknown", protection: protectionWithoutBypassAllowance(), expectedCode: "protection_malformed" },
    { ownerType: "Organization", protection: protectionFixture(), expectedCode: "fixture_stop" },
  ];
  for (const { ownerType, protection, expectedCode } of cases) {
    const calls = [];
    const state = executableEvidence({ pullRequest: true });
    const fixture = executionFixture({
      state,
      calls,
      protection,
      repositoryOwnerType: ownerType,
      mergeError: new ReleaseAutomationError("fixture_stop", "Stop after branch protection validation."),
    });
    await assert.rejects(
      () => runReleaseAutomation({
        phase: "execute",
        ...fixture,
        input: { state },
        config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
        clock: { now: () => Date.now(), sleep: async () => {} },
      }),
      (error) => error instanceof ReleaseAutomationError && error.code === expectedCode,
    );
    assert.equal(calls.some(([name]) => name === "repository"), true);
    assert.equal(calls.some(([name]) => name === "protection"), true);
    assert.equal(calls.some(([name]) => name === "merge"), expectedCode === "fixture_stop");
  }
});

test("an ordinary user PR cannot enter the automated release merge path", async () => {
  const calls = [];
  const state = executableEvidence({ pullRequest: true });
  const fixture = executionFixture({ state, calls, protection: protectionFixture(), pullRequestUserType: "User" });
  await assert.rejects(
    () => runReleaseAutomation({
      phase: "execute",
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
      clock: { now: () => Date.now(), sleep: async () => {} },
    }),
    (error) => error instanceof ReleaseAutomationError && error.code === "candidate_identity_mismatch",
  );
  assert.deepEqual(calls.map(([name]) => name), ["actor", "origin-run", "actor", "artifact", "pulls", "runs", "commit", "commit", "tree", "blob", "pr"]);
});

test("concrete GitHub REST adapter maps protected squash identity and artifact metadata endpoints", async () => {
  const calls = [];
  const auth = {
    async request(method, endpoint, body) {
      calls.push({ method, endpoint, body });
      if (endpoint.endsWith("/merge")) return { merged: true, sha: SHA, merge_commit_sha: SHA };
      return {
        id: 901,
        name: "release-op-1-preparation-attempt-1",
        digest: `sha256:${DIGEST}`,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        workflow_run: {
          id: 77,
          repository_id: REPOSITORY_ID,
          head_repository_id: REPOSITORY_ID,
          head_sha: SHA,
        },
      };
    },
  };
  const api = new GitHubRestApi({ auth, repository: "owner/media-finder" });
  await api.mergePullRequest(12, { merge_method: "squash", expected_head_sha: SHA });
  await api.getArtifact(901);
  assert.deepEqual(calls[0], {
    method: "PUT",
    endpoint: "/repos/owner/media-finder/pulls/12/merge",
    body: { merge_method: "squash", sha: SHA },
  });
  assert.deepEqual(calls[1], {
    method: "GET",
    endpoint: "/repos/owner/media-finder/actions/artifacts/901",
    body: undefined,
  });
  assert.throws(
    () => api.mergePullRequest(12, { merge_method: "merge", expected_head_sha: SHA }),
    (error) => error instanceof ReleaseAutomationError && error.code === "merge_policy_violation",
  );
});

test("Actions artifact transport uses the maintained four-argument SDK and renews findBy before downloads", async () => {
  const calls = [];
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), "release-artifact-test-"));
  const digest = `sha256:${DIGEST}`;
  const artifact = evidence();
  let renewals = 0;
  const client = {
    async uploadArtifact(...args) {
      calls.push({ method: "uploadArtifact", args });
      // The maintained SDK reports the provider hash without the REST
      // `sha256:` prefix.
      return { id: 901, digest: DIGEST };
    },
    async getArtifact(...args) {
      calls.push({ method: "getArtifact", args });
      return { artifact: { id: 901, name: args[0], digest: DIGEST } };
    },
    async downloadArtifact(...args) {
      calls.push({ method: "downloadArtifact", args });
      const [, options] = args;
      await fsp.writeFile(path.join(options.path, "release-evidence.json"), `${JSON.stringify(artifact)}\n`);
      return { downloadPath: options.path, digestMismatch: false };
    },
  };
  try {
    const store = await createActionsArtifactStore({
      client,
      repository: "owner/media-finder",
      workflowRunId: 77,
      metadataReader: async () => ({
        id: 901,
        name: "release-op-1-preparation-attempt-1",
        digest,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        workflow_run: {
          id: 77,
          repository_id: REPOSITORY_ID,
          head_repository_id: REPOSITORY_ID,
          head_sha: SHA,
        },
      }),
      tokenProvider: async () => ({ token: `token-${++renewals}` }),
      temporaryDirectory: root,
    });
    const uploaded = await store.upload({ name: "release-op-1-preparation-attempt-1", content: `${JSON.stringify(artifact)}\n` });
    assert.equal(uploaded.id, 901);
    assert.equal(uploaded.digest, digest);
    const uploadCall = calls.find((call) => call.method === "uploadArtifact");
    assert.equal(uploadCall.args.length, 4);
    assert.equal(uploadCall.args[0], "release-op-1-preparation-attempt-1");
    assert.equal(path.basename(uploadCall.args[1][0]), "release-evidence.json");
    assert.equal(uploadCall.args[2].startsWith(root), true);
    assert.deepEqual(uploadCall.args[3], { retentionDays: 90 });
    const lookup = calls.find((call) => call.method === "getArtifact");
    assert.equal(lookup.args[0], "release-op-1-preparation-attempt-1");
    assert.deepEqual(lookup.args[1].findBy, {
      token: "token-1",
      workflowRunId: 77,
      repositoryOwner: "owner",
      repositoryName: "media-finder",
    });

    const recovered = await store.read(901, { digest, workflowRunId: 77 });
    assert.equal(recovered.contentDigest, artifact.contentDigest);
    const downloadCall = calls.find((call) => call.method === "downloadArtifact");
    assert.equal(downloadCall.args[0], 901);
    assert.equal(downloadCall.args[1].expectedHash, digest);
    assert.deepEqual(downloadCall.args[1].findBy, {
      token: "token-2",
      workflowRunId: 77,
      repositoryOwner: "owner",
      repositoryName: "media-finder",
    });
    assert.equal(renewals, 2);
  } finally {
    await fsp.rm(root, { recursive: true, force: true });
  }
});

test("Actions artifact transport fails closed on SDK digest mismatch", async () => {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), "release-artifact-digest-test-"));
  const client = {
    async uploadArtifact() { return { id: 902, digest: `sha256:${DIGEST}` }; },
    async getArtifact(name) { return { artifact: { id: 902, name, digest: `sha256:${DIGEST}` } }; },
    async downloadArtifact() { return { digestMismatch: true }; },
  };
  try {
    const store = await createActionsArtifactStore({ client, repository: "owner/media-finder", workflowRunId: 77, token: "fixture-token", temporaryDirectory: root });
    await assert.rejects(
      () => store.read(902, { digest: DIGEST, workflowRunId: 77 }),
      (error) => error instanceof ReleaseAutomationError && error.code === "artifact_digest_mismatch",
    );
  } finally {
    await fsp.rm(root, { recursive: true, force: true });
  }
});

function restPullRequest({ headSha = SHA, baseSha = SHA } = {}) {
  return {
    number: 12,
    head: {
      ref: "release-op-1-v0.5.0-attempt-1",
      sha: headSha,
      repo: {
        id: REPOSITORY_ID,
        name: "media-finder",
        url: "https://api.github.com/repos/owner/media-finder",
      },
    },
    base: {
      ref: "main",
      sha: baseSha,
      repo: {
        id: REPOSITORY_ID,
        name: "media-finder",
        url: "https://api.github.com/repos/owner/media-finder",
      },
    },
  };
}

function restWorkflowRun({
  id = 700,
  event = "pull_request",
  path = CI_WORKFLOW_PATH,
  headSha = SHA,
  baseSha = SHA,
  runAttempt = 2,
  status = "completed",
  conclusion = "success",
  pullRequests = event === "pull_request" ? [restPullRequest({ headSha, baseSha })] : [],
} = {}) {
  return {
    id,
    run_attempt: runAttempt,
    status,
    conclusion,
    event,
    path,
    head_sha: headSha,
    head_branch: event === "push" ? "main" : "release-op-1-v0.5.0-attempt-1",
    repository_id: REPOSITORY_ID,
    head_repository_id: REPOSITORY_ID,
    pull_requests: pullRequests,
  };
}

function restCheckRuns(run, statuses = {}) {
  return REQUIRED_CHECK_CONTEXTS.map((context, index) => {
    const id = run.id * 10 + index;
    return {
      id,
      url: `https://api.github.com/repos/owner/media-finder/check-runs/${id}`,
      name: context,
      head_sha: run.head_sha,
      status: statuses[context]?.status ?? "completed",
      conclusion: statuses[context]?.conclusion ?? "success",
      app: { id: GITHUB_ACTIONS_APP_ID, slug: "github-actions" },
      check_suite: { id: run.id * 100, head_sha: run.head_sha },
    };
  });
}

function restJobs(run, statuses = {}, { includeEdge = false, includeAttempt = false } = {}) {
  const jobs = REQUIRED_CHECK_CONTEXTS.map((context, index) => {
    const id = run.id * 10 + index;
    const name = context.split(" / ").at(-1);
    return {
      id,
      name,
      run_id: run.id,
      ...(includeAttempt ? { run_attempt: run.run_attempt } : {}),
      head_sha: run.head_sha,
      status: statuses[context]?.status ?? "completed",
      conclusion: statuses[context]?.conclusion ?? "success",
      check_run_url: `https://api.github.com/repos/owner/media-finder/check-runs/${id}`,
    };
  });
  if (includeEdge) {
    jobs.push({
      id: run.id * 10 + 99,
      name: "publish-edge",
      run_id: run.id,
      ...(includeAttempt ? { run_attempt: run.run_attempt } : {}),
      head_sha: run.head_sha,
      status: "completed",
      conclusion: "success",
    });
  }
  return jobs;
}

test("required checks use one exact CI run, PR base association, and attempt-bound jobs", () => {
  const run = restWorkflowRun({ path: "owner/media-finder/.github/workflows/ci.yaml@main" });
  const result = evaluateRequiredChecks(restCheckRuns(run), {
    headSha: SHA,
    baseSha: SHA,
    repository: "owner/media-finder",
    repositoryId: REPOSITORY_ID,
    workflowRuns: [run],
    workflowJobs: { total_count: 7, jobs: restJobs(run) },
  });
  assert.equal(result.state, "passed");
  assert.deepEqual(Object.values(result.statuses), Array(7).fill("success"));
});

test("missing or stale required evidence remains pending instead of becoming a failure", () => {
  const run = restWorkflowRun({ runAttempt: 2 });
  const missing = evaluateRequiredChecks([], {
    headSha: SHA,
    baseSha: SHA,
    repository: "owner/media-finder",
    repositoryId: REPOSITORY_ID,
    workflowRuns: [],
    workflowJobs: [],
  });
  assert.equal(missing.state, "pending");

  const staleJobs = restJobs({ ...run, run_attempt: 1 }, {}, { includeAttempt: true });
  assert.equal(
    evaluateRequiredChecks(restCheckRuns(run), {
      headSha: SHA,
      baseSha: SHA,
      repository: "owner/media-finder",
      repositoryId: REPOSITORY_ID,
      workflowRuns: [run],
      workflowJobs: { total_count: 7, jobs: staleJobs },
    }).state,
    "pending",
  );
});

test("failed, skipped, and cancelled current checks block the candidate", () => {
  const run = restWorkflowRun();
  for (const conclusion of ["failure", "skipped", "cancelled"]) {
    const statuses = { [REQUIRED_CHECK_CONTEXTS[2]]: { conclusion } };
    const result = evaluateRequiredChecks(restCheckRuns(run, statuses), {
      headSha: SHA,
      baseSha: SHA,
      repository: "owner/media-finder",
      repositoryId: REPOSITORY_ID,
      workflowRuns: [run],
      workflowJobs: { total_count: 7, jobs: restJobs(run, statuses) },
    });
    assert.equal(result.state, "failed", conclusion);
  }
});

test("workflow_call, suffix paths, and name-only checks fail closed", () => {
  const workflowCall = restWorkflowRun({ event: "workflow_call" });
  assert.throws(
    () => evaluateRequiredChecks(restCheckRuns(workflowCall), {
      headSha: SHA,
      baseSha: SHA,
      repository: "owner/media-finder",
      repositoryId: REPOSITORY_ID,
      workflowRuns: [workflowCall],
      workflowJobs: { total_count: 7, jobs: restJobs(workflowCall) },
    }),
    (error) => error instanceof ReleaseAutomationError && error.code === "untrusted_workflow",
  );

  const wrongPath = restWorkflowRun({ path: ".github/workflows/ci.yaml.backup" });
  assert.throws(
    () => evaluateRequiredChecks(restCheckRuns(wrongPath), {
      headSha: SHA,
      baseSha: SHA,
      repository: "owner/media-finder",
      repositoryId: REPOSITORY_ID,
      workflowRuns: [wrongPath],
      workflowJobs: { total_count: 7, jobs: restJobs(wrongPath) },
    }),
    (error) => error instanceof ReleaseAutomationError && error.code === "untrusted_workflow",
  );

  for (const path of [
    "owner/media-finder/.github/workflows/CI.yaml@main",
    "evil/media-finder/.github/workflows/ci.yaml@main",
    "owner/media-finder/.github/workflows/ci.yaml@MAIN",
  ]) {
    const wrongQualifiedPath = restWorkflowRun({ path });
    assert.throws(
      () => evaluateRequiredChecks(restCheckRuns(wrongQualifiedPath), {
        headSha: SHA,
        baseSha: SHA,
        repository: "owner/media-finder",
        repositoryId: REPOSITORY_ID,
        workflowRuns: [wrongQualifiedPath],
        workflowJobs: { total_count: 7, jobs: restJobs(wrongQualifiedPath) },
      }),
      (error) => error instanceof ReleaseAutomationError && error.code === "untrusted_workflow",
    );
  }

  const nameOnly = restCheckRuns(restWorkflowRun()).map(({ name }) => ({ name, conclusion: "success" }));
  assert.equal(
    evaluateRequiredChecks(nameOnly, {
      headSha: SHA,
      baseSha: SHA,
      repository: "owner/media-finder",
      repositoryId: REPOSITORY_ID,
      workflowRuns: [],
      workflowJobs: [],
    }).state,
    "pending",
  );
});

test("workflow jobs are fetched from the exact run-attempt REST endpoint", async () => {
  const calls = [];
  const api = new GitHubRestApi({
    repository: "owner/media-finder",
    auth: {
      async request(method, endpoint, body) {
        calls.push({ method, endpoint, body });
        return { total_count: 0, jobs: [] };
      },
    },
  });
  await api.getWorkflowRunJobs(700, 2);
  assert.deepEqual(calls, [{
    method: "GET",
    endpoint: "/repos/owner/media-finder/actions/runs/700/attempts/2/jobs?per_page=100",
    body: undefined,
  }]);
});

test("workflow-run lookup uses the documented workflow filename route", async () => {
  const calls = [];
  const api = new GitHubRestApi({
    repository: "owner/media-finder",
    auth: {
      async request(method, endpoint, body) {
        calls.push({ method, endpoint, body });
        return { total_count: 0, workflow_runs: [] };
      },
    },
  });
  await api.getWorkflowRuns({ workflow: CI_WORKFLOW_PATH, headSha: SHA, event: "push", branch: "main" });
  assert.deepEqual(calls, [{
    method: "GET",
    endpoint: "/repos/owner/media-finder/actions/workflows/ci.yaml/runs?per_page=100&head_sha=" + SHA + "&event=push&branch=main",
    body: undefined,
  }]);
});

test("workflow-run selection orders newer runs before older attempts", () => {
  const older = restWorkflowRun({ id: 720, runAttempt: 3 });
  older.created_at = "2026-01-01T00:00:00Z";
  const newer = restWorkflowRun({ id: 721, runAttempt: 1 });
  newer.created_at = "2026-01-02T00:00:00Z";
  const result = evaluateRequiredChecks(restCheckRuns(newer), {
    headSha: SHA,
    baseSha: SHA,
    repository: "owner/media-finder",
    repositoryId: REPOSITORY_ID,
    workflowRuns: [older, newer],
    workflowJobs: { total_count: 7, jobs: restJobs(newer) },
  });
  assert.equal(result.state, "passed");
  assert.equal(result.workflowRunId, newer.id);
  assert.equal(result.workflowRunAttempt, newer.run_attempt);
});

test("release identity requires exact target, notes, stable flags, and draft state", () => {
  const notes = "# Media Finder v0.5.0\n\nAutomatically generated from repository history. Not editorially reviewed.";
  const release = {
    id: 77,
    tag_name: "v0.5.0",
    target_commitish: SHA,
    body: notes,
    draft: true,
    prerelease: false,
  };
  assert.doesNotThrow(() => assertReleaseMetadata(release, {
    tag: "v0.5.0",
    mergedSha: SHA,
    notes,
    draft: true,
  }));
  for (const altered of [
    { ...release, target_commitish: "main" },
    { ...release, body: `${notes}\nchanged` },
    { ...release, prerelease: true },
    { ...release, draft: "true" },
    { ...release, tag_name: "v0.5.1" },
  ]) {
    assert.throws(() => assertReleaseMetadata(altered, {
      tag: "v0.5.0",
      mergedSha: SHA,
      notes,
      draft: true,
    }), ReleaseAutomationError);
  }
});

test("main publication requires one exact CI push run and all jobs in its current attempt", async () => {
  const run = restWorkflowRun({ id: 710, event: "push", runAttempt: 3, path: "owner/media-finder/.github/workflows/ci.yaml@main" });
  const calls = [];
  const api = {
    async getWorkflowRuns(input) {
      calls.push(["runs", input]);
      return { total_count: 1, workflow_runs: [run] };
    },
    async getWorkflowRunJobs(...args) {
      calls.push(["jobs", ...args]);
      return { total_count: 8, jobs: restJobs(run, {}, { includeEdge: true }) };
    },
  };
  const result = await checkMainPublication(api, { ensureToken: async () => {} }, SHA, {
    repository: "owner/media-finder",
    repositoryId: REPOSITORY_ID,
  });
  assert.equal(result.state, "passed");
  assert.deepEqual(calls[0], ["runs", { headSha: SHA, event: "push", branch: "main", workflow: CI_WORKFLOW_PATH }]);
  assert.deepEqual(calls[1], ["jobs", run.id, run.run_attempt]);
});

test("latest stable release ignores drafts and target_commitish and peels an annotated tag", async () => {
  const annotatedTagObject = "c".repeat(40);
  const actualCommit = "d".repeat(40);
  const api = {
    async listReleases() {
      return [
        { tag_name: "v9.9.9", draft: true, prerelease: false, target_commitish: actualCommit },
        { tag_name: "v8.8.8", prerelease: false, target_commitish: actualCommit },
        { tag_name: "v7.7.7", draft: false, target_commitish: actualCommit },
        { tag_name: "v2.0.0", draft: false, prerelease: false, target_commitish: "main" },
        { tag_name: "v1.9.9", draft: false, prerelease: true, target_commitish: actualCommit },
      ];
    },
    async getTagRef(tag) {
      assert.equal(tag, "v2.0.0");
      return { ref: "refs/tags/v2.0.0", object: { type: "tag", sha: annotatedTagObject } };
    },
    async getTag(sha) {
      assert.equal(sha, annotatedTagObject);
      return { object: { type: "commit", sha: actualCommit } };
    },
  };
  const latest = await readLatestStable(api, { ensureToken: async () => {} });
  assert.equal(latest.tag, "v2.0.0");
  assert.equal(latest.sha, actualCommit);
});

test("stable version ordering remains exact for canonical large components", () => {
  assert.equal(compareStableVersions("9007199254740993.0.0", "9007199254740992.0.0"), 1);
  assert.throws(
    () => compareStableVersions("1.000000000000000000000.0", "1.0.0"),
    ReleaseAutomationError,
  );
});

function canonicalPublication({
  state = "published",
  version = "0.5.0",
  revision = SHA,
  runId = 808,
  releaseURL = "https://github.com/owner/media-finder/releases/tag/v0.5.0",
} = {}) {
  const digest = `sha256:${DIGEST}`;
  const names = [`v${version}`, "0.5", "latest"];
  const actualTags = names.map((name) => ({
    name,
    tag: name,
    reference: `ghcr.io/owner/media-finder:${name}`,
    digest,
    platforms: [
      { name: "linux/amd64", digest: `sha256:${"1".repeat(64)}`, sourceRevision: revision, version },
      { name: "linux/arm64", digest: `sha256:${"2".repeat(64)}`, sourceRevision: revision, version },
    ],
    sourceRevision: revision,
  }));
  return {
    schemaVersion: 1,
    operation: "stable-image-publication",
    state,
    image: "ghcr.io/owner/media-finder",
    version,
    releaseTag: `v${version}`,
    sourceRevision: revision,
    digest,
    platforms: ["linux/amd64", "linux/arm64"],
    actualTags,
    workflowURL: `https://github.com/owner/media-finder/actions/runs/${runId}`,
    releaseURL,
  };
}

test("publication evidence requires the publisher canonical actualTags and trusted URLs", () => {
  const publication = canonicalPublication();
  const checked = validatePublicationEvidence(publication, {
    repository: "owner/media-finder",
    version: "0.5.0",
    mergedSha: SHA,
    runId: 808,
    releaseURL: publication.releaseURL,
  });
  assert.deepEqual(checked.actualTags.map(({ name }) => name), ["v0.5.0", "0.5", "latest"]);
  assert.equal(checked.digest, `sha256:${DIGEST}`);

  assert.throws(
    () => validatePublicationEvidence({ ...publication, actualTags: undefined, tags: publication.actualTags }, {
      repository: "owner/media-finder",
      version: "0.5.0",
      mergedSha: SHA,
      runId: 808,
      releaseURL: publication.releaseURL,
    }),
    ReleaseAutomationError,
  );
});

test("stable publication waits for exact release run and downloads its canonical evidence artifact", async () => {
  const run = restWorkflowRun({ id: 808, event: "release", path: "owner/media-finder/.github/workflows/release.yaml@main", runAttempt: 4 });
  const publication = canonicalPublication({ runId: run.id });
  const artifact = {
    id: 909,
    name: `stable-publication-evidence-${run.id}-${run.run_attempt}`,
    digest: `sha256:${"3".repeat(64)}`,
    expires_at: new Date(Date.now() + 3600000).toISOString(),
    expired: false,
    workflow_run: {
      id: run.id,
      repository_id: REPOSITORY_ID,
      head_repository_id: REPOSITORY_ID,
      head_sha: SHA,
    },
  };
  const calls = [];
  const api = {
    async getWorkflowRuns(input) {
      calls.push(["runs", input]);
      return { total_count: 1, workflow_runs: [run] };
    },
    async listRunArtifacts(runId) {
      calls.push(["artifacts", runId]);
      return { total_count: 1, artifacts: [artifact] };
    },
    async getArtifact(id) {
      calls.push(["artifact", id]);
      return artifact;
    },
  };
  const artifacts = {
    async read(id, options) {
      calls.push(["read", id, options]);
      return publication;
    },
  };
  const result = await waitForPublication(api, { ensureToken: async () => {} }, artifacts, undefined, {
    repository: "owner/media-finder",
    repositoryId: REPOSITORY_ID,
    version: "0.5.0",
    mergedSha: SHA,
    releaseId: 55,
    releaseUrl: publication.releaseURL,
  }, { clock: { now: () => Date.now(), sleep: async () => {} } });
  assert.equal(result.state, "passed");
  assert.equal(result.publication.actualTags.length, 3);
  assert.deepEqual(calls[0], ["runs", { headSha: SHA, event: "release", workflow: RELEASE_WORKFLOW_PATH }]);
  assert.deepEqual(calls.at(-1), ["read", artifact.id, {
    digest: "3".repeat(64),
    expectedFilename: "release-publication-evidence.json",
    workflowRunId: run.id,
  }]);
});

test("recursive tree verification rejects an unsupported gitlink entry", async () => {
  const api = new GitHubRestApi({
    repository: "owner/media-finder",
    auth: {
      async request(method, endpoint) {
        assert.equal(method, "GET");
        if (endpoint.includes("/git/trees/")) {
          return {
            truncated: false,
            tree: [{ type: "commit", mode: "160000", path: "vendor", sha: SHA }],
          };
        }
        throw new Error(`unexpected endpoint: ${endpoint}`);
      },
    },
  });
  await assert.rejects(
    () => api.getTreeDigest(SHA),
    (error) => error instanceof ReleaseAutomationError && error.code === "tree_digest_unavailable",
  );
});

const PREPARATION_BASE_TREE_SHA = "c".repeat(40);
const PREPARATION_TREE_SHA = "d".repeat(40);
const PREPARATION_COMMIT_SHA = "e".repeat(40);
const PREPARATION_BLOB_SHAS = ["1".repeat(40), "2".repeat(40)];

function preparationWorkingTreeDigest(files) {
  const digest = crypto.createHash("sha256");
  for (const file of [...files].sort((left, right) => left.path < right.path ? -1 : left.path > right.path ? 1 : 0)) {
    const content = Buffer.from(file.content);
    digest.update(file.path).update("\0").update(file.mode).update("\0");
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(content.length));
    digest.update(length).update(content);
  }
  return digest.digest("hex");
}

async function preparationFixture({ uploadFailure = false, metadataFailure, readbackFailure, omitSnapshot = false, historyPages } = {}) {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), "release-preparation-intent-test-"));
  const notes = "# Media Finder v0.5.0\n\nAutomatically generated from repository history. Not editorially reviewed.\n";
  await fsp.writeFile(path.join(root, "VERSION"), "0.4.0\n", "utf8");
  const { execFile: execFileCallback } = await import("node:child_process");
  const execFile = (await import("node:util")).promisify(execFileCallback);
  await execFile("git", ["init", "-q"], { cwd: root });
  await execFile("git", ["add", "VERSION"], { cwd: root });

  const candidateFiles = [
    { path: "VERSION", mode: "100644", content: "0.5.0\n" },
    { path: "docs/releases/0.5.0.md", mode: "100644", content: notes },
  ];

  const snapshot = {
    throughSha: SHA,
    commits: [{ sha: SHA, url: `https://github.com/owner/media-finder/commit/${SHA}` }],
  };
  const candidateTreeSha256 = preparationWorkingTreeDigest(candidateFiles);
  const expectedTree = Object.fromEntries(candidateFiles.map((file) => [file.path, {
    mode: file.mode,
    sha256: sha256(file.content),
  }]));
  const baseTreeSha256 = preparationWorkingTreeDigest([{ path: "VERSION", mode: "100644", content: "0.4.0\n" }]);
  const calls = [];
  const blobContents = new Map();
  const treeEntries = [];
  let uploadedPayload;
  const metadata = {
    id: 901,
    name: "release-op-1-preparation-attempt-1",
    digest: `sha256:${DIGEST}`,
    expires_at: new Date(Date.now() + 3600000).toISOString(),
    expired: false,
    workflow_run: {
      id: 77,
      repository_id: REPOSITORY_ID,
      head_repository_id: REPOSITORY_ID,
      head_sha: SHA,
    },
  };
  const api = {
    async getCollaboratorPermission(...args) {
      calls.push(["actor", ...args]);
      return { permission: "push" };
    },
    async getRepository(...args) {
      calls.push(["repository", ...args]);
      return { id: REPOSITORY_ID, full_name: "owner/media-finder" };
    },
    async getRef(...args) {
      calls.push(["ref", ...args]);
      return { object: { sha: SHA } };
    },
    async listReleases(...args) {
      calls.push(["releases", ...args]);
      return [{ tag_name: "v0.4.0", draft: false, prerelease: false }];
    },
    async getTagRef(...args) {
      calls.push(["tag", ...args]);
      return { object: { type: "commit", sha: SHA } };
    },
    async getCommit(shaValue) {
      calls.push(["commit", shaValue]);
      if (shaValue === SHA) return { tree: { sha: PREPARATION_BASE_TREE_SHA }, parents: [] };
      assert.equal(shaValue, PREPARATION_COMMIT_SHA);
      return { tree: { sha: PREPARATION_TREE_SHA }, parents: [{ sha: SHA }] };
    },
    async createBlob(content) {
      calls.push(["createBlob", content]);
      const index = blobContents.size;
      const blobSha = PREPARATION_BLOB_SHAS[index];
      blobContents.set(blobSha, Buffer.from(content));
      return { sha: blobSha };
    },
    async createTree(input) {
      calls.push(["createTree", input]);
      assert.equal(input.base_tree, PREPARATION_BASE_TREE_SHA);
      treeEntries.push(...input.tree);
      return { sha: PREPARATION_TREE_SHA };
    },
    async createCommit(input) {
      calls.push(["createCommit", input]);
      assert.deepEqual(input.parents, [SHA]);
      assert.equal(input.tree, PREPARATION_TREE_SHA);
      return { sha: PREPARATION_COMMIT_SHA };
    },
    async getTree(shaValue) {
      calls.push(["tree", shaValue]);
      assert.equal(shaValue, PREPARATION_TREE_SHA);
      return { truncated: false, tree: treeEntries };
    },
    async getBlob(shaValue) {
      calls.push(["blob", shaValue]);
      return { encoding: "base64", content: blobContents.get(shaValue).toString("base64") };
    },
    async getArtifact(...args) {
      calls.push(["artifact", ...args]);
      if (metadataFailure === "missing") return { id: 901, name: metadata.name };
      if (metadataFailure === "wrong-run") return { ...metadata, workflow_run: { ...metadata.workflow_run, id: 78 } };
      return { ...metadata };
    },
    async getWorkflowRuns(...args) {
      calls.push(["discovery-runs", ...args]);
      return { total_count: 0, workflow_runs: [] };
    },
    async listRunArtifacts(...args) {
      calls.push(["run-artifacts", ...args]);
      return { total_count: 0, artifacts: [] };
    },
    async compareCommits(base, head, options = {}) {
      calls.push(["compare", base, head, options]);
      if (!historyPages) return { total_commits: 0, commits: [] };
      const page = Number(options.page ?? 1);
      const value = historyPages[page - 1];
      if (!value) return { commits: [] };
      return value;
    },
    async getCommitPullRequests(sha) {
      calls.push(["commit-pulls", sha]);
      return [];
    },
  };
  const artifacts = {
    async upload({ name, content }) {
      calls.push(["upload", name]);
      if (uploadFailure) throw new ReleaseAutomationError("artifact_upload_failed", "fixture upload failed");
      uploadedPayload = JSON.parse(content);
      return { ...metadata, name };
    },
    async read(id, options) {
      calls.push(["read", id, options]);
      assert.equal(id, metadata.id);
      if (readbackFailure === "altered") return { ...uploadedPayload, preparedTreeSha: PREPARATION_BASE_TREE_SHA };
      if (readbackFailure === "missing") return undefined;
      return uploadedPayload;
    },
  };
  const auth = {
    current: {
      identity: {
        appId: 123,
        appSlug: "media-finder-release",
        installationId: 456,
        repository: "owner/media-finder",
        repositoryId: REPOSITORY_ID,
      },
    },
    async ensureToken() {},
  };
  const context = {
    eventName: "workflow_dispatch",
    ref: "refs/heads/main",
    repository: "owner/media-finder",
    actor: "maintainer",
    sha: SHA,
    runId: 77,
    runAttempt: 1,
  };
  let capturedSnapshot;
  const preparer = {
    async prepare({ root: preparationRoot, version, snapshot: preparationSnapshot, baseSha: preparedBase, previousStableTag, previousStableSha }) {
      capturedSnapshot = preparationSnapshot;
      assert.equal(preparationRoot, root);
      assert.equal(version, "0.5.0");
      if (!omitSnapshot) assert.deepEqual(preparationSnapshot, snapshot);
      await fsp.mkdir(path.join(root, "docs/releases"), { recursive: true });
      await fsp.writeFile(path.join(root, "VERSION"), candidateFiles[0].content, "utf8");
      await fsp.writeFile(path.join(root, candidateFiles[1].path), notes, "utf8");
      return {
        schema_version: 1,
        version: "0.5.0",
        base_commit: preparedBase ?? SHA,
        previous_stable_tag: previousStableTag ?? "v0.4.0",
        previous_stable_sha: previousStableSha ?? SHA,
        snapshot_sha256: sha256(`${canonicalJson(preparationSnapshot)}\n`),
        base_tree_sha256: baseTreeSha256,
        candidate_tree_sha256: candidateTreeSha256,
        notes_path: candidateFiles[1].path,
        changed_files: candidateFiles.map(({ path: filePath }) => filePath),
        expected_tree: expectedTree,
      };
    },
  };
  return {
    root,
    calls,
    api,
    auth,
    artifacts,
    context,
    preparer,
    candidateFiles,
    notes,
    expectedTree,
    baseTreeSha256,
    candidateTreeSha256,
    input: {
      version: "0.5.0",
      currentVersion: "0.4.0",
      ...(omitSnapshot ? {} : { notesInputSnapshot: snapshot }),
      operationId: "release-op-1",
    },
    config: {
      allowedActors: ["maintainer"],
      trustedControllerSha: SHA,
      statePath: path.join(root, "preparation.json"),
      evidencePath: path.join(root, "evidence.json"),
    },
    metadata,
    get uploadedPayload() {
      return uploadedPayload;
    },
    get capturedSnapshot() {
      return capturedSnapshot;
    },
  };
}

async function runPreparationFixture(options = {}) {
  const fixture = await preparationFixture(options);
  try {
    const result = await runReleaseAutomation({
      phase: "prepare",
      api: fixture.api,
      auth: fixture.auth,
      artifacts: fixture.artifacts,
      context: fixture.context,
      preparer: fixture.preparer,
      input: fixture.input,
      config: fixture.config,
      cwd: fixture.root,
    });
    return { fixture, result };
  } catch (error) {
    return { fixture, error };
  }
}

test("prepare persists verified unreachable commit and tree identities before artifact readback", async () => {
  const { fixture, result, error } = await runPreparationFixture();
  if (!result) throw error;
  assert.equal(result.state.preparedCommitSha, PREPARATION_COMMIT_SHA);
  assert.equal(result.state.preparedTreeSha, PREPARATION_TREE_SHA);
  assert.equal(fixture.uploadedPayload.preparedCommitSha, PREPARATION_COMMIT_SHA);
  assert.equal(fixture.uploadedPayload.preparedTreeSha, PREPARATION_TREE_SHA);
  assert.equal(fixture.uploadedPayload.contentDigest, result.state.contentDigest);
  const commitIndex = fixture.calls.findIndex(([name]) => name === "createCommit");
  const uploadIndex = fixture.calls.findIndex(([name]) => name === "upload");
  const readIndex = fixture.calls.findIndex(([name]) => name === "read");
  assert.equal(commitIndex >= 0, true);
  assert.equal(uploadIndex > commitIndex, true);
  assert.equal(readIndex > uploadIndex, true);
  assert.equal(fixture.calls.some(([name]) => name === "createRef" || name === "createPullRequest"), false);
  assert.deepEqual(fixture.calls.at(-1), ["read", 901, {
    digest: DIGEST,
    expectedFilename: "release-evidence.json",
    workflowRunId: 77,
  }]);
});

test("prepare upload, metadata, and readback failures never expose a branch or PR", async () => {
  for (const options of [
    { uploadFailure: true },
    { metadataFailure: "missing" },
    { metadataFailure: "wrong-run" },
    { readbackFailure: "altered" },
    { readbackFailure: "missing" },
  ]) {
    const { fixture, error } = await runPreparationFixture(options);
    assert.equal(error instanceof ReleaseAutomationError, true);
    assert.equal(fixture.calls.some(([name]) => name === "createRef" || name === "createPullRequest"), false);
  }
});

function executionIntentFixture({
  branchMode = "matching",
  commitTreeSha,
  parentSha,
  pullRequestMerged = false,
  releaseConclusion = "success",
  releaseRunStatus = "completed",
  releaseRunPath = RELEASE_WORKFLOW_PATH,
  createPullRequestError,
  listPullRequestsResults,
  pullRequestPatch,
} = {}) {
  const state = executableEvidence();
  const releaseNotes = "Automatically generated from repository history. Not editorially reviewed.";
  if (pullRequestMerged) {
    state.prNumber = 12;
    state.prHeadSha = state.preparedCommitSha;
    state.prBaseSha = SHA;
  }
  state.notesPath = "VERSION";
  state.candidateFiles[0].content = releaseNotes;
  state.expectedTree.files.VERSION.sha256 = sha256(releaseNotes);
  state.expectedTree.digest = preparationWorkingTreeDigest(state.candidateFiles);
  state.candidateTreeSha256 = state.expectedTree.digest;
  delete state.contentDigest;
  const digestInput = { ...state };
  delete digestInput.artifact;
  state.contentDigest = sha256(canonicalJson(digestInput));
  const preparedCommitSha = state.preparedCommitSha;
  const preparedTreeSha = state.preparedTreeSha;
  const branch = "release-op-1-v0.5.0-attempt-1";
  const branchSha = branchMode === "conflicting" ? "9".repeat(40) : preparedCommitSha;
  const calls = [];
  let branchReads = 0;
  const metadata = {
    id: 901,
    name: "release-op-1-preparation-attempt-1",
    digest: `sha256:${DIGEST}`,
    expires_at: new Date(Date.now() + 3600000).toISOString(),
    expired: false,
    workflow_run: {
      id: 77,
      repository_id: REPOSITORY_ID,
      head_repository_id: REPOSITORY_ID,
      head_sha: SHA,
    },
  };
  const api = {
    async getCollaboratorPermission(...args) {
      calls.push(["actor", ...args]);
      return { permission: "push" };
    },
    async getArtifact(...args) {
      calls.push(["artifact", ...args]);
      return metadata;
    },
    async getWorkflowRunAttempt(...args) {
      calls.push(["origin-run", ...args]);
      return {
        id: 77,
        run_attempt: args[1],
        status: "completed",
        conclusion: "success",
        event: "workflow_dispatch",
        path: "owner/media-finder/.github/workflows/prepare-release.yaml@main",
        head_sha: SHA,
        head_branch: "main",
        actor: { login: "maintainer", type: "User" },
        repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
        head_repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
        repository_id: REPOSITORY_ID,
        head_repository_id: REPOSITORY_ID,
      };
    },
    async getRepository(...args) {
      calls.push(["repository", ...args]);
      return {
        id: REPOSITORY_ID,
        full_name: "owner/media-finder",
        owner: { type: "User", login: "owner" },
      };
    },
    async getWorkflowRuns(input) {
      calls.push(["runs", input]);
      if (input.event === "push") {
        const run = restWorkflowRun({ id: 710, event: "push", headSha: SHA, runAttempt: 1 });
        return { total_count: 1, workflow_runs: [run] };
      }
      if (input.event === "release") {
        const run = restWorkflowRun({
          id: 808,
          event: "release",
          headSha: SHA,
          runAttempt: 1,
          status: releaseRunStatus,
          conclusion: releaseConclusion,
          path: releaseRunPath,
        });
        return { total_count: 1, workflow_runs: [run] };
      }
      return { total_count: 0, workflow_runs: [] };
    },
    async getWorkflowRunJobs(...args) {
      calls.push(["jobs", ...args]);
      const run = restWorkflowRun({ id: 710, event: "push", headSha: SHA, runAttempt: args[1] });
      return { total_count: 8, jobs: restJobs(run, {}, { includeEdge: true }) };
    },
    async listReleases(...args) {
      calls.push(["releases", ...args]);
      return [{
        id: 55,
        tag_name: "v0.5.0",
        target_commitish: SHA,
        body: releaseNotes,
        draft: false,
        prerelease: false,
        html_url: "https://github.com/owner/media-finder/releases/tag/v0.5.0",
      }];
    },
    async getRelease(...args) {
      calls.push(["release", ...args]);
      return {
        id: 55,
        tag_name: "v0.5.0",
        target_commitish: SHA,
        body: releaseNotes,
        draft: false,
        prerelease: false,
        html_url: "https://github.com/owner/media-finder/releases/tag/v0.5.0",
      };
    },
    async getTagRef(...args) {
      calls.push(["tag", ...args]);
      return { ref: "refs/tags/v0.5.0", object: { type: "commit", sha: SHA } };
    },
    async listPullRequests(...args) {
      calls.push(["pulls", ...args]);
      if (listPullRequestsResults !== undefined) {
        const next = listPullRequestsResults.shift();
        return next ?? [];
      }
      return [];
    },
    async listRunArtifacts(...args) {
      calls.push(["run-artifacts", ...args]);
      return { total_count: 0, artifacts: [] };
    },
    async getBranchProtection(...args) {
      calls.push(["protection", ...args]);
      return protectionFixture();
    },
    async getCommit(shaValue) {
      calls.push(["commit", shaValue]);
      assert.equal(shaValue === preparedCommitSha || (pullRequestMerged && shaValue === SHA), true);
      return {
        tree: { sha: commitTreeSha ?? preparedTreeSha },
        parents: [{ sha: parentSha ?? state.baseSha }],
      };
    },
    async getTree(shaValue) {
      calls.push(["tree", shaValue]);
      assert.equal(shaValue, preparedTreeSha);
      return {
        truncated: false,
        tree: [{ path: "VERSION", mode: "100644", type: "blob", sha: sha256(releaseNotes) }],
      };
    },
    async getBlob(shaValue) {
      calls.push(["blob", shaValue]);
      assert.equal(shaValue, sha256(releaseNotes));
      return { encoding: "base64", content: Buffer.from(releaseNotes).toString("base64") };
    },
    async getRef(ref) {
      calls.push(["ref", ref]);
      if (ref === "heads/main") return { object: { sha: state.baseSha } };
      assert.equal(ref, `heads/${branch}`);
      branchReads += 1;
      if (branchMode === "missing-then-matching" && branchReads === 1) {
        throw new ReleaseAutomationError("github_api_error", "Not found.", { status: 404 });
      }
      if (branchMode === "missing") {
        throw new ReleaseAutomationError("github_api_error", "Not found.", { status: 404 });
      }
      return { object: { sha: branchSha } };
    },
    async createRef(...args) {
      calls.push(["createRef", ...args]);
      assert.deepEqual(args, [`refs/heads/${branch}`, preparedCommitSha]);
      if (branchMode === "missing-then-matching") {
        throw new ReleaseAutomationError("token_expired", "Token expired.");
      }
      return { ref: `refs/heads/${branch}`, object: { sha: preparedCommitSha } };
    },
    async createPullRequest(input) {
      calls.push(["createPullRequest", input]);
      assert.equal(input.head, branch);
      assert.equal(input.base, "main");
      if (createPullRequestError) throw createPullRequestError;
      const created = {
        number: 12,
        state: "open",
        head: { sha: preparedCommitSha, ref: branch, repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
        base: { ref: "main", sha: state.baseSha, repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
        user: { login: "media-finder-release[bot]", type: "Bot" },
      };
      return pullRequestPatch ? pullRequestPatch(created) : created;
    },
    async getPullRequest(...args) {
      calls.push(["pr", ...args]);
      const pullRequest = {
        number: 12,
        state: pullRequestMerged ? "closed" : "open",
        ...(pullRequestMerged ? { merged: true, merged_at: "2026-01-02T00:00:00Z", merge_commit_sha: SHA } : {}),
        head: { sha: preparedCommitSha, ref: branch, repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
        base: { ref: "main", sha: state.baseSha, repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
        user: { login: "media-finder-release[bot]", type: "Bot" },
      };
      return pullRequestPatch ? pullRequestPatch(pullRequest) : pullRequest;
    },
  };
  const artifacts = {
    async read(id, options) {
      calls.push(["read", id, options]);
      return state;
    },
  };
  return {
    state,
    calls,
    api,
    artifacts,
    auth: {
      current: {
        identity: {
          appId: 123,
          appSlug: "media-finder-release",
          installationId: 456,
          repository: "owner/media-finder",
          repositoryId: REPOSITORY_ID,
        },
      },
      async ensureToken() {},
    },
    context: {
      eventName: "workflow_dispatch",
      ref: "refs/heads/main",
      repository: "owner/media-finder",
      actor: "maintainer",
      sha: SHA,
      runId: 77,
      runAttempt: 1,
    },
    config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    input: { state },
  };
}

async function runExecutionIntentFixture(options = {}) {
  const fixture = executionIntentFixture(options);
  try {
    const result = await runReleaseAutomation({
      phase: "execute",
      ...fixture,
      clock: { now: () => Date.now(), sleep: async () => {} },
    });
    return { fixture, result };
  } catch (error) {
    return { fixture, error };
  }
}

test("failed stable publication cannot report complete after an authentic merged release", async () => {
  for (const releaseConclusion of ["failure", "cancelled", "skipped"]) {
    const { fixture, result, error } = await runExecutionIntentFixture({
      pullRequestMerged: true,
      releaseConclusion,
    });
    assert.equal(result, undefined);
    assert.equal(error instanceof ReleaseAutomationError, true);
    assert.equal(error.code, "publication_failed");
    assert.equal(error.details.releaseId, 55);
    assert.equal(error.details.releaseUrl, "https://github.com/owner/media-finder/releases/tag/v0.5.0");
    assert.equal(error.details.workflowRunId, 808);
    assert.equal(error.details.workflowRunAttempt, 1);
    assert.equal(fixture.calls.some(([name]) => name === "release"), true);
  }
});

test("execute reuses the durable prepared SHA without regenerating Git objects", async () => {
  const { fixture, error } = await runExecutionIntentFixture({ branchMode: "matching" });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "review_threads_unavailable");
  assert.equal(fixture.calls.some(([name]) => ["createBlob", "createTree", "createCommit"].includes(name)), false);
  assert.equal(fixture.calls.some(([name]) => name === "createRef"), false);
  const pr = fixture.calls.find(([name]) => name === "createPullRequest");
  assert.equal(pr[1].head, "release-op-1-v0.5.0-attempt-1");
  assert.equal(fixture.calls.some(([name, input]) => name === "createPullRequest" && input.head === fixture.state.preparedCommitSha), false);
});

test("execute stops on prepared tree or parent mismatch and conflicting ref", async () => {
  for (const options of [
    { commitTreeSha: "8".repeat(40) },
    { parentSha: "8".repeat(40) },
    { branchMode: "conflicting" },
  ]) {
    const { fixture, error } = await runExecutionIntentFixture(options);
    assert.equal(error instanceof ReleaseAutomationError, true);
    assert.equal(error.code, options.branchMode === "conflicting" ? "branch_conflict" : "candidate_identity_mismatch");
    assert.equal(fixture.calls.some(([name]) => name === "createRef" || name === "createPullRequest"), false);
  }
});

test("execute reconciles an uncertain ref creation and reuses the exact prepared SHA", async () => {
  const { fixture, error } = await runExecutionIntentFixture({ branchMode: "missing-then-matching" });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "review_threads_unavailable");
  const createRef = fixture.calls.find(([name]) => name === "createRef");
  assert.deepEqual(createRef, ["createRef", "refs/heads/release-op-1-v0.5.0-attempt-1", fixture.state.preparedCommitSha]);
  assert.equal(fixture.calls.filter(([name]) => name === "ref").length, 3);
  assert.equal(fixture.calls.some(([name]) => ["createBlob", "createTree", "createCommit"].includes(name)), false);
});

test("execute discovers the original preparation across dispatches without local state", async () => {
  const fixture = executionIntentFixture({ branchMode: "matching" });
  const temporaryRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "release-cross-dispatch-test-"));
  const currentSha = "c".repeat(40);
  const originRun = {
    id: 77,
    run_attempt: 1,
    status: "completed",
    conclusion: "success",
    event: "workflow_dispatch",
    path: "owner/media-finder/.github/workflows/prepare-release.yaml@main",
    head_sha: SHA,
    head_branch: "main",
    actor: { login: "maintainer", type: "User" },
    repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
    head_repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
    repository_id: REPOSITORY_ID,
    head_repository_id: REPOSITORY_ID,
  };
  const listedRun = { ...originRun, run_attempt: 2 };
  fixture.context = { ...fixture.context, sha: currentSha, runId: 99, runAttempt: 2 };
  fixture.config = {
    ...fixture.config,
    trustedControllerSha: currentSha,
    repositoryId: REPOSITORY_ID,
    statePath: path.join(temporaryRoot, "preparation.json"),
    evidencePath: path.join(temporaryRoot, "evidence.json"),
  };
  fixture.input = { version: "0.5.0", currentVersion: "0.4.0" };
  fixture.auth.current = {
    identity: {
      appId: 123,
      appSlug: "media-finder-release",
      installationId: 456,
      repository: "owner/media-finder",
      repositoryId: REPOSITORY_ID,
    },
  };
  fixture.api.getWorkflowRuns = async (input) => {
    fixture.calls.push(["discovery-runs", input]);
    if (input.event === "workflow_dispatch") return { total_count: 1, workflow_runs: [listedRun] };
    return { total_count: 0, workflow_runs: [] };
  };
  fixture.api.getWorkflowRunAttempt = async (...args) => {
    fixture.calls.push(["origin-run", ...args]);
    if (args[1] === 2) return listedRun;
    if (args[1] === 1) return originRun;
    throw new Error(`unexpected attempt ${args[1]}`);
  };
  fixture.api.listRunArtifacts = async (...args) => {
    fixture.calls.push(["run-artifacts", ...args]);
    return { total_count: 1, artifacts: [{ id: 901, name: "release-op-1-preparation-attempt-1" }] };
  };

  try {
    const { error } = await runExecutionIntentFixtureWithFixture(fixture);
    assert.equal(error instanceof ReleaseAutomationError, true);
    assert.equal(error.code, "review_threads_unavailable");
    assert.equal(fixture.calls.some(([name]) => name === "discovery-runs"), true);
    assert.equal(fixture.calls.some(([name]) => name === "origin-run"), true);
    assert.equal(fixture.calls.some(([name, runId, attempt]) => name === "origin-run" && runId === 77 && attempt === 1), true);
    assert.equal(fixture.calls.some(([name]) => name === "run-artifacts"), true);
    const readCalls = fixture.calls.filter(([name]) => name === "read");
    assert.equal(readCalls.length >= 1, true);
    assert.equal(readCalls[0][2].workflowRunId, 77);
    assert.equal(fixture.calls.some(([name]) => name === "createBlob" || name === "createCommit"), false);
  } finally {
    await fsp.rm(temporaryRoot, { recursive: true, force: true });
  }
});

test("recovery accepts durable preparation evidence regardless of run conclusion", async () => {
  for (const [status, conclusion] of [["completed", "failure"], ["completed", "cancelled"], ["completed", "timed_out"]]) {
    const origin = preparationDiscoveryRun({ status, conclusion });
    const { error } = await runRecoveryFixture({ originAttempts: { "77:1": origin } });
    assert.equal(error instanceof ReleaseAutomationError, true, conclusion);
    assert.equal(error.code, "review_threads_unavailable", conclusion);
  }

  const inProgress = preparationDiscoveryRun({ status: "in_progress", conclusion: null });
  const { error } = await runRecoveryFixture({
    listedRuns: [inProgress],
    originAttempts: { "77:1": inProgress },
    currentSha: SHA,
    currentRunId: 77,
    currentRunAttempt: 1,
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "review_threads_unavailable");
});

function preparationDiscoveryRun({
  id = 77,
  runAttempt = 1,
  headSha = SHA,
  event = "workflow_dispatch",
  workflowPath = "owner/media-finder/.github/workflows/prepare-release.yaml@main",
  headBranch = "main",
  actor = "maintainer",
  status = "completed",
  conclusion = "success",
  repositoryId = REPOSITORY_ID,
  headRepositoryId = repositoryId,
  repository = "owner/media-finder",
  headRepository = repository,
} = {}) {
  return {
    id,
    run_attempt: runAttempt,
    status,
    conclusion,
    event,
    path: workflowPath,
    head_sha: headSha,
    head_branch: headBranch,
    actor: { login: actor, type: "User" },
    repository: { id: repositoryId, full_name: repository },
    head_repository: { id: headRepositoryId, full_name: headRepository },
    repository_id: repositoryId,
    head_repository_id: headRepositoryId,
  };
}

function recoveryPayload(value, overrides = {}) {
  const payload = { ...value, ...overrides };
  delete payload.contentDigest;
  const digestInput = { ...payload };
  delete digestInput.artifact;
  payload.contentDigest = sha256(canonicalJson(digestInput));
  return payload;
}

async function runRecoveryFixture({
  phase = "execute",
  listedRuns,
  artifactLists,
  metadataById = {},
  payloadById = {},
  originAttempts = {},
  pulls,
  branches,
  currentSha = "c".repeat(40),
  currentRunId = 99,
  currentRunAttempt = 2,
  patchApi,
} = {}) {
  const fixture = executionIntentFixture({ branchMode: "matching" });
  const temporaryRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "release-recovery-discovery-test-"));
  const originalWorkflowRuns = fixture.api.getWorkflowRuns;
  const defaultListedRun = preparationDiscoveryRun({ runAttempt: 2 });
  const defaultOriginRun = preparationDiscoveryRun({ runAttempt: 1 });
  const runs = listedRuns ?? [defaultListedRun];
  const defaultArtifacts = [{ id: 901, name: "release-op-1-preparation-attempt-1" }];
  const lists = artifactLists ?? { 77: defaultArtifacts };
  const defaultMetadata = {
    id: 901,
    name: "release-op-1-preparation-attempt-1",
    digest: `sha256:${DIGEST}`,
    expires_at: new Date(Date.now() + 3600000).toISOString(),
    expired: false,
    workflow_run: {
      id: 77,
      repository_id: REPOSITORY_ID,
      head_repository_id: REPOSITORY_ID,
      head_sha: SHA,
    },
  };
  fixture.context = {
    ...fixture.context,
    sha: currentSha,
    runId: currentRunId,
    runAttempt: currentRunAttempt,
  };
  fixture.config = {
    ...fixture.config,
    trustedControllerSha: currentSha,
    repositoryId: REPOSITORY_ID,
    statePath: path.join(temporaryRoot, "preparation.json"),
    evidencePath: path.join(temporaryRoot, "evidence.json"),
  };
  fixture.input = { version: "0.5.0", currentVersion: "0.4.0" };
  fixture.api.getWorkflowRuns = async (input) => {
    fixture.calls.push(["discovery-runs", input]);
    if (input.event === "workflow_dispatch") return { total_count: runs.length, workflow_runs: runs };
    return originalWorkflowRuns.call(fixture.api, input);
  };
  fixture.api.getWorkflowRunAttempt = async (runId, runAttempt) => {
    fixture.calls.push(["origin-run", runId, runAttempt]);
    const override = originAttempts[`${runId}:${runAttempt}`];
    if (override) return override;
    if (Number(runId) === 77 && Number(runAttempt) === 1) return defaultOriginRun;
    if (Number(runId) === 77 && Number(runAttempt) === 2) return defaultListedRun;
    const listed = runs.find((run) => Number(run.id) === Number(runId));
    if (listed && Number(listed.run_attempt) === Number(runAttempt)) return listed;
    throw new Error(`unexpected origin attempt ${runId}:${runAttempt}`);
  };
  fixture.api.listRunArtifacts = async (runId) => {
    fixture.calls.push(["run-artifacts", runId]);
    return { total_count: (lists[runId] ?? []).length, artifacts: lists[runId] ?? [] };
  };
  fixture.api.getArtifact = async (artifactId) => {
    fixture.calls.push(["artifact", artifactId]);
    if (Object.hasOwn(metadataById, artifactId)) return metadataById[artifactId];
    const hint = Object.values(lists).flat().find((item) => Number(item.id) === Number(artifactId));
    return { ...defaultMetadata, id: Number(artifactId), name: hint?.name ?? defaultMetadata.name };
  };
  fixture.artifacts.read = async (artifactId, options) => {
    fixture.calls.push(["read", artifactId, options]);
    if (Object.hasOwn(payloadById, artifactId)) return payloadById[artifactId];
    return fixture.state;
  };
  if (pulls !== undefined) {
    fixture.api.listPullRequests = async (...args) => {
      fixture.calls.push(["pulls", ...args]);
      return pulls;
    };
  }
  if (branches !== undefined) {
    fixture.api.listBranches = async (...args) => {
      fixture.calls.push(["branches", ...args]);
      return branches;
    };
  }
  patchApi?.(fixture.api, fixture.calls);
  try {
    const result = await runReleaseAutomation({
      phase,
      ...fixture,
      clock: { now: () => Date.now(), sleep: async () => {} },
    });
    return { fixture, result };
  } catch (error) {
    return { fixture, error };
  } finally {
    await fsp.rm(temporaryRoot, { recursive: true, force: true });
  }
}

test("recovery discovery binds the original run actor, repository, workflow, and SHA", async () => {
  const cases = [
    {
      name: "actor",
      origin: preparationDiscoveryRun({ actor: "stranger" }),
      code: "unauthorized_actor",
    },
    {
      name: "workflow",
      origin: preparationDiscoveryRun({ workflowPath: "owner/media-finder/.github/workflows/other.yaml@main" }),
      code: "untrusted_workflow",
    },
    {
      name: "event",
      origin: preparationDiscoveryRun({ event: "push" }),
      code: "untrusted_workflow",
    },
    {
      name: "head SHA",
      origin: preparationDiscoveryRun({ headSha: "d".repeat(40) }),
      code: "artifact_provenance_mismatch",
    },
    {
      name: "repository scope",
      origin: preparationDiscoveryRun({ repositoryId: REPOSITORY_ID + 1 }),
      code: "untrusted_workflow",
    },
    {
      name: "fork scope",
      origin: preparationDiscoveryRun({ headRepositoryId: REPOSITORY_ID + 1, headRepository: "evil/fork" }),
      code: "untrusted_workflow",
    },
  ];
  for (const { name, origin, code } of cases) {
    const { fixture, error } = await runRecoveryFixture({
      originAttempts: { "77:1": origin },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, name);
    assert.equal(error.code, code, name);
    assert.equal(fixture.calls.some(([method]) => method === "createRef" || method === "createPullRequest"), false, name);
  }

  const forgedPayload = recoveryPayload(executableEvidence(), { trustedControllerSha: "d".repeat(40) });
  const { error } = await runRecoveryFixture({ payloadById: { 901: forgedPayload } });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "controller_revision_mismatch");

  const missingAttemptSource = executableEvidence();
  delete missingAttemptSource.originRunAttempt;
  const missingAttempt = await runRecoveryFixture({
    payloadById: { 901: recoveryPayload(missingAttemptSource) },
  });
  assert.equal(missingAttempt.error instanceof ReleaseAutomationError, true);
  assert.equal(missingAttempt.error.code, "artifact_provenance_mismatch");

  for (const [field, code] of [["appId", "app_identity_mismatch"], ["installationId", "installation_mismatch"]]) {
    const mismatchedIdentity = await runRecoveryFixture({
      payloadById: { 901: recoveryPayload(executableEvidence(), { [field]: 999 }) },
    });
    assert.equal(mismatchedIdentity.error instanceof ReleaseAutomationError, true, field);
    assert.equal(mismatchedIdentity.error.code, code, field);
  }
});

test("recovery discovery rejects missing, expired, and digest-inconsistent artifacts", async () => {
  const missing = await runRecoveryFixture({
    artifactLists: { 77: [{ id: 901, name: `${DETERMINISTIC_PREPARATION_OPERATION_ID}-preparation-attempt-1` }] },
    metadataById: { 901: { id: 901, name: `${DETERMINISTIC_PREPARATION_OPERATION_ID}-preparation-attempt-1` } },
  });
  assert.equal(missing.error instanceof ReleaseAutomationError, true);
  assert.equal(missing.error.code, "artifact_digest_mismatch");

  const deleted = await runRecoveryFixture({
    artifactLists: { 77: [{ id: 901, name: `${DETERMINISTIC_PREPARATION_OPERATION_ID}-preparation-attempt-1` }] },
    payloadById: { 901: undefined },
  });
  assert.equal(deleted.error instanceof ReleaseAutomationError, true);
  assert.equal(deleted.error.code, "artifact_schema_invalid");

  const misleadingName = await runRecoveryFixture({
    artifactLists: { 77: [{ id: 901, name: "release-other-operation-preparation-attempt-1" }] },
  });
  assert.equal(misleadingName.error instanceof ReleaseAutomationError, true);
  assert.equal(misleadingName.error.code, "artifact_identity_mismatch");

  const expired = await runRecoveryFixture({
    artifactLists: { 77: [{ id: 901, name: `${DETERMINISTIC_PREPARATION_OPERATION_ID}-preparation-attempt-1` }] },
    metadataById: {
      901: {
        id: 901,
        name: `${DETERMINISTIC_PREPARATION_OPERATION_ID}-preparation-attempt-1`,
        digest: `sha256:${DIGEST}`,
        expires_at: new Date(Date.now() - 1000).toISOString(),
        workflow_run: { id: 77, repository_id: REPOSITORY_ID, head_repository_id: REPOSITORY_ID, head_sha: SHA },
      },
    },
  });
  assert.equal(expired.error instanceof ReleaseAutomationError, true);
  assert.equal(expired.error.code, "artifact_expired");

  const digest = "c".repeat(64);
  const inconsistent = await runRecoveryFixture({
    artifactLists: { 77: [{ id: 901, name: `${DETERMINISTIC_PREPARATION_OPERATION_ID}-preparation-attempt-1`, digest: `sha256:${DIGEST}` }] },
    metadataById: {
      901: {
        id: 901,
        name: `${DETERMINISTIC_PREPARATION_OPERATION_ID}-preparation-attempt-1`,
        digest: `sha256:${digest}`,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        workflow_run: { id: 77, repository_id: REPOSITORY_ID, head_repository_id: REPOSITORY_ID, head_sha: SHA },
      },
    },
  });
  assert.equal(inconsistent.error instanceof ReleaseAutomationError, true);
  assert.equal(inconsistent.error.code, "artifact_digest_mismatch");
});

test("recovery discovery blocks multiple operations, ambiguous attempts, and conflicting branch state", async () => {
  const secondRun = preparationDiscoveryRun({ id: 78, runAttempt: 1 });
  const secondPayload = recoveryPayload(executableEvidence(), {
    operationId: "release-op-2",
    originRunId: 78,
    originRunAttempt: 1,
  });
  const duplicateOperations = await runRecoveryFixture({
    listedRuns: [preparationDiscoveryRun({ runAttempt: 2 }), secondRun],
    artifactLists: {
      77: [{ id: 901, name: "release-op-1-preparation-attempt-1" }],
      78: [{ id: 902, name: "release-op-2-preparation-attempt-1" }],
    },
    metadataById: {
      902: {
        id: 902,
        name: "release-op-2-preparation-attempt-1",
        digest: `sha256:${DIGEST}`,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        workflow_run: { id: 78, repository_id: REPOSITORY_ID, head_repository_id: REPOSITORY_ID, head_sha: SHA },
      },
    },
    payloadById: { 902: secondPayload },
    originAttempts: { "78:1": secondRun },
  });
  assert.equal(duplicateOperations.error instanceof ReleaseAutomationError, true);
  assert.equal(duplicateOperations.error.code, "duplicate_release_state");

  const secondAttemptPayload = recoveryPayload(executableEvidence(), {
    attempt: 2,
    originRunAttempt: 2,
  });
  const ambiguousAttempts = await runRecoveryFixture({
    artifactLists: {
      77: [
        { id: 901, name: "release-op-1-preparation-attempt-1" },
        { id: 902, name: "release-op-1-preparation-attempt-2" },
      ],
    },
    metadataById: {
      902: {
        id: 902,
        name: "release-op-1-preparation-attempt-2",
        digest: `sha256:${DIGEST}`,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        workflow_run: { id: 77, repository_id: REPOSITORY_ID, head_repository_id: REPOSITORY_ID, head_sha: SHA },
      },
    },
    payloadById: { 902: secondAttemptPayload },
    originAttempts: { "77:2": preparationDiscoveryRun({ runAttempt: 2 }) },
  });
  assert.equal(ambiguousAttempts.error instanceof ReleaseAutomationError, true);
  assert.equal(ambiguousAttempts.error.code, "duplicate_release_state");

  const conflicting = await runRecoveryFixture({
    listedRuns: [],
    artifactLists: {},
    branches: [{ name: "release-op-1-v0.5.0-attempt-1" }],
  });
  assert.equal(conflicting.error instanceof ReleaseAutomationError, true);
  assert.equal(conflicting.error.code, "duplicate_release_state");
});

test("prepare discovers an authenticated same-version artifact before generating a duplicate", async () => {
  const fixture = await preparationFixture();
  const existing = evidence();
  const origin = preparationDiscoveryRun({ runAttempt: 1 });
  fixture.api.getWorkflowRuns = async (...args) => {
    fixture.calls.push(["discovery-runs", ...args]);
    return { total_count: 1, workflow_runs: [origin] };
  };
  fixture.api.getWorkflowRunAttempt = async (...args) => {
    fixture.calls.push(["origin-run", ...args]);
    return origin;
  };
  fixture.api.listRunArtifacts = async (...args) => {
    fixture.calls.push(["run-artifacts", ...args]);
    return { total_count: 1, artifacts: [{ id: 901, name: "release-op-1-preparation-attempt-1" }] };
  };
  fixture.artifacts.read = async (id, options) => {
    fixture.calls.push(["read", id, options]);
    return existing;
  };
  try {
    await assert.rejects(
      () => runReleaseAutomation({
        phase: "prepare",
        ...fixture,
        cwd: fixture.root,
      }),
      (error) => error instanceof ReleaseAutomationError && error.code === "duplicate_release_state",
    );
    assert.equal(fixture.calls.some(([name]) => ["createBlob", "createTree", "createCommit", "upload"].includes(name)), false);
  } finally {
    await fsp.rm(fixture.root, { recursive: true, force: true });
  }
});

test("prepare ignores expired artifacts for unrelated historical versions", async () => {
  const fixture = await preparationFixture();
  const origin = preparationDiscoveryRun({ runAttempt: 1 });
  const unrelatedName = "release-old-operation-preparation-attempt-1";
  const expiredMetadata = {
    ...fixture.metadata,
    id: 902,
    name: unrelatedName,
    expires_at: new Date(Date.now() - 1000).toISOString(),
  };
  const originalGetArtifact = fixture.api.getArtifact;
  fixture.api.getWorkflowRuns = async (...args) => {
    fixture.calls.push(["discovery-runs", ...args]);
    return { total_count: 1, workflow_runs: [origin] };
  };
  fixture.api.getWorkflowRunAttempt = async (...args) => {
    fixture.calls.push(["origin-run", ...args]);
    return origin;
  };
  fixture.api.listRunArtifacts = async (...args) => {
    fixture.calls.push(["run-artifacts", ...args]);
    return { total_count: 1, artifacts: [{ id: 902, name: unrelatedName }] };
  };
  fixture.api.getArtifact = async (id) => id === 902 ? expiredMetadata : originalGetArtifact(id);
  try {
    const result = await runReleaseAutomation({
      phase: "prepare",
      ...fixture,
      cwd: fixture.root,
    });
    assert.equal(result.state.version, "0.5.0");
    assert.equal(fixture.calls.some(([name]) => name === "upload"), true);
  } finally {
    await fsp.rm(fixture.root, { recursive: true, force: true });
  }
});

async function runExecutionIntentFixtureWithFixture(fixture) {
  try {
    const result = await runReleaseAutomation({
      phase: "execute",
      ...fixture,
      clock: { now: () => Date.now(), sleep: async () => {} },
    });
    return { fixture, result };
  } catch (error) {
    return { fixture, error };
  }
}

// ---------------------------------------------------------------------------
// Trusted orchestration: request phase, App bot identity, identity-bound PR
// creation, credential-free regeneration, and complete history capture.
// ---------------------------------------------------------------------------

async function runPhaseFixture(phase, fixture) {
  try {
    const result = await runReleaseAutomation({
      phase,
      ...fixture,
      clock: { now: () => Date.now(), sleep: async () => {} },
    });
    return { fixture, result };
  } catch (error) {
    return { fixture, error };
  }
}

// Reaches the protected squash-merge mutation: PR identity, all seven required
// checks, and the pre-merge gates must all be satisfiable in the fixture.
function mergeIntentFixture(options = {}) {
  const fixture = executionIntentFixture({ branchMode: "matching", ...options });
  const { calls, state } = fixture;
  const candidateRun = () => restWorkflowRun({
    id: 700,
    runAttempt: 1,
    headSha: state.preparedCommitSha,
    baseSha: state.baseSha,
  });
  fixture.api.getCheckRuns = async (...args) => {
    calls.push(["checks", ...args]);
    return { check_runs: restCheckRuns(candidateRun()) };
  };
  const baseGetWorkflowRuns = fixture.api.getWorkflowRuns;
  fixture.api.getWorkflowRuns = async (input) => {
    if (input.event === "pull_request") {
      calls.push(["runs", input]);
      return { total_count: 1, workflow_runs: [candidateRun()] };
    }
    return baseGetWorkflowRuns(input);
  };
  fixture.api.getWorkflowRunJobs = async (...args) => {
    calls.push(["jobs", ...args]);
    return { total_count: 7, jobs: restJobs(candidateRun()) };
  };
  fixture.api.listReviewThreads = async (...args) => {
    calls.push(["threads", ...args]);
    return [];
  };
  fixture.api.listReviewRequests = async (...args) => {
    calls.push(["requests", ...args]);
    return { users: [], teams: [] };
  };
  fixture.api.listReviews = async (...args) => {
    calls.push(["reviews", ...args]);
    return [];
  };
  fixture.api.mergePullRequest = async (...args) => {
    calls.push(["merge", ...args]);
    throw options.mergeError ?? new ReleaseAutomationError("fixture_stop", "Stop after the protected squash merge request.");
  };
  fixture.preparer = options.preparer ?? regenerationPreparer(state, {
    calls,
    alter: options.regenerationAlter,
    onCheckout: options.onCheckout,
  });
  return fixture;
}

test("release request phase composes the flow, requires a version, and still fails closed", async () => {
  const state = executableEvidence({ pullRequest: true });
  const calls = [];
  const fixture = executionFixture({
    state,
    calls,
    protection: protectionFixture(),
    mergeError: new ReleaseAutomationError("fixture_stop", "Stop after the protected squash merge request."),
  });
  const config = { allowedActors: ["maintainer"], trustedControllerSha: SHA };

  const unknown = await runPhaseFixture("unknown-phase", { ...fixture, input: { state, version: "0.5.0" }, config });
  assert.equal(unknown.error instanceof ReleaseAutomationError, true);
  assert.equal(unknown.error.code, "phase_invalid");

  const missingVersion = await runPhaseFixture("request", { ...fixture, input: { state }, config });
  assert.equal(missingVersion.error instanceof ReleaseAutomationError, true);
  assert.equal(missingVersion.error.code, "invalid_version");

  const requested = await runPhaseFixture("request", { ...fixture, input: { state, version: "0.5.0" }, config });
  assert.equal(requested.error instanceof ReleaseAutomationError, true);
  assert.notEqual(requested.error.code, "phase_invalid");
  assert.equal(requested.error.code, "fixture_stop");
  assert.equal(calls.some(([name]) => name === "merge"), true);
  assert.equal(calls.some(([name]) => ["createRef", "createPullRequest"].includes(name)), false);
});

test("release request reuses an authenticated same-version preparation instead of duplicating it", async () => {
  const fixture = executionIntentFixture({ branchMode: "matching" });
  const temporaryRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "release-request-resume-test-"));
  const currentSha = "c".repeat(40);
  const originRun = {
    id: 77,
    run_attempt: 1,
    status: "completed",
    conclusion: "success",
    event: "workflow_dispatch",
    path: "owner/media-finder/.github/workflows/prepare-release.yaml@main",
    head_sha: SHA,
    head_branch: "main",
    actor: { login: "maintainer", type: "User" },
    repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
    head_repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
    repository_id: REPOSITORY_ID,
    head_repository_id: REPOSITORY_ID,
  };
  const listedRun = { ...originRun, run_attempt: 2 };
  fixture.context = { ...fixture.context, sha: currentSha, runId: 99, runAttempt: 2 };
  fixture.config = {
    ...fixture.config,
    trustedControllerSha: currentSha,
    repositoryId: REPOSITORY_ID,
    statePath: path.join(temporaryRoot, "preparation.json"),
    evidencePath: path.join(temporaryRoot, "evidence.json"),
  };
  fixture.input = { version: "0.5.0", currentVersion: "0.4.0" };
  fixture.api.getWorkflowRuns = async (input) => {
    fixture.calls.push(["discovery-runs", input]);
    if (input.event === "workflow_dispatch") return { total_count: 1, workflow_runs: [listedRun] };
    return { total_count: 0, workflow_runs: [] };
  };
  fixture.api.getWorkflowRunAttempt = async (...args) => {
    fixture.calls.push(["origin-run", ...args]);
    if (args[1] === 2) return listedRun;
    if (args[1] === 1) return originRun;
    throw new Error(`unexpected attempt ${args[1]}`);
  };
  fixture.api.listRunArtifacts = async (...args) => {
    fixture.calls.push(["run-artifacts", ...args]);
    return { total_count: 1, artifacts: [{ id: 901, name: "release-op-1-preparation-attempt-1" }] };
  };
  try {
    const { error } = await runPhaseFixture("request", fixture);
    assert.equal(error instanceof ReleaseAutomationError, true);
    assert.equal(error.code, "review_threads_unavailable");
    assert.equal(fixture.calls.some(([name]) => name === "discovery-runs"), true);
    assert.equal(fixture.calls.some(([name]) => ["createBlob", "createTree", "createCommit", "upload"].includes(name)), false);
    assert.equal(fixture.calls.filter(([name]) => name === "read").length >= 1, true);
    assert.equal(
      fixture.calls.filter(([name, , options]) => name === "read" && options?.workflowRunId === 77).length >= 1,
      true,
    );
  } finally {
    await fsp.rm(temporaryRoot, { recursive: true, force: true });
  }
});

test("release pull request identity is mandatory, exact, and cannot be substituted", async () => {
  const cases = [
    { name: "missing base repository id", patch: (pr) => { delete pr.base.repo.id; return pr; } },
    { name: "missing base SHA", patch: (pr) => { delete pr.base.sha; return pr; } },
    { name: "advanced base SHA", code: "base_changed", patch: (pr) => { pr.base.sha = "b".repeat(40); return pr; } },
    { name: "wrong base ref", patch: (pr) => { pr.base.ref = "release"; return pr; } },
    { name: "missing head repository id", patch: (pr) => { delete pr.head.repo.id; return pr; } },
    { name: "missing head ref", patch: (pr) => { delete pr.head.ref; return pr; } },
    { name: "forged head ref", patch: (pr) => { pr.head.ref = "release-forged-v0.5.0-attempt-1"; return pr; } },
    { name: "wrong head SHA", patch: (pr) => { pr.head.sha = "d".repeat(40); return pr; } },
    { name: "missing author", patch: (pr) => { delete pr.user; return pr; } },
    { name: "bot type without an authenticated login", patch: (pr) => { pr.user = { type: "Bot" }; return pr; } },
    { name: "label-only release claim from a user", patch: (pr) => { pr.labels = [{ name: "release" }]; pr.user = { login: "outsider", type: "User" }; return pr; } },
    { name: "forged App bot login", patch: (pr) => { pr.user = { login: "attacker[bot]", type: "Bot" }; return pr; } },
  ];
  for (const { name, code = "candidate_identity_mismatch", patch } of cases) {
    const calls = [];
    const state = executableEvidence({ pullRequest: true });
    const fixture = executionFixture({ state, calls, protection: protectionFixture(), pullRequestPatch: patch });
    const { error } = await runPhaseFixture("execute", {
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, name);
    assert.equal(error.code, code, name);
    assert.equal(calls.some(([method]) => method === "merge"), false, name);
    assert.equal(calls.some(([method]) => ["createRef", "createPullRequest", "updatePullRequest"].includes(method)), false, name);
  }
});

test("an uncertain release pull request creation is reconciled against live state", async () => {
  for (const failure of [
    new ReleaseAutomationError("github_unavailable", "Network failure after the mutation."),
    new ReleaseAutomationError("github_api_error", "Bad gateway.", { status: 502 }),
    new ReleaseAutomationError("token_expired", "Token expired after the mutation."),
  ]) {
    const fixture = executionIntentFixture({
      branchMode: "matching",
      createPullRequestError: failure,
      // First listing: same-version conflict check. Second: reconcile before
      // create finds nothing. Third: live state after the uncertain mutation.
      listPullRequestsResults: [[], [], [{ number: 12, head: { ref: "release-op-1-v0.5.0-attempt-1" } }]],
    });
    const { error } = await runPhaseFixture("execute", fixture);
    assert.equal(error instanceof ReleaseAutomationError, true, failure.code);
    assert.equal(error.code, "review_threads_unavailable", failure.code);
    assert.equal(fixture.calls.filter(([name]) => name === "createPullRequest").length, 1, failure.code);
    assert.equal(fixture.calls.some(([name]) => name === "createRef"), false, failure.code);
    assert.deepEqual(fixture.calls.find(([name]) => name === "pr").slice(0, 2), ["pr", 12], failure.code);
    assert.equal(fixture.calls.some(([name]) => name === "merge"), false, failure.code);
  }
});

test("an authentic existing release pull request is adopted before creation", async () => {
  const fixture = executionIntentFixture({
    branchMode: "matching",
    listPullRequestsResults: [[], [{ number: 12, head: { ref: "release-op-1-v0.5.0-attempt-1" } }]],
  });
  const { error } = await runPhaseFixture("execute", fixture);
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "review_threads_unavailable");
  assert.equal(fixture.calls.some(([name]) => name === "createPullRequest"), false);
  assert.deepEqual(fixture.calls.find(([name]) => name === "pr").slice(0, 2), ["pr", 12]);
});

test("a forged pull request on the generated branch stops before creation", async () => {
  const fixture = executionIntentFixture({
    branchMode: "matching",
    listPullRequestsResults: [[], [{ number: 12, head: { ref: "release-op-1-v0.5.0-attempt-1" } }]],
    pullRequestPatch: (pr) => { pr.user = { login: "attacker[bot]", type: "Bot" }; return pr; },
  });
  const { error } = await runPhaseFixture("execute", fixture);
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "candidate_identity_mismatch");
  assert.equal(fixture.calls.some(([name]) => ["createPullRequest", "updatePullRequest", "createRef"].includes(name)), false);
});

test("an uncertain release pull request creation stops on conflicting live state", async () => {
  const fixture = executionIntentFixture({
    branchMode: "matching",
    createPullRequestError: new ReleaseAutomationError("github_unavailable", "Network failure after the mutation."),
    listPullRequestsResults: [[], [], [{ number: 12, head: { ref: "release-op-1-v0.5.0-attempt-1" } }]],
    pullRequestPatch: (pr) => { pr.head.sha = "d".repeat(40); return pr; },
  });
  const { error } = await runPhaseFixture("execute", fixture);
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "candidate_identity_mismatch");
  assert.equal(fixture.calls.filter(([name]) => name === "createPullRequest").length, 1);
  assert.equal(fixture.calls.some(([name]) => ["updatePullRequest", "createRef", "mergePullRequest"].includes(name)), false);
});

test("credential-free regeneration is reproduced and compared immediately before merge", async () => {
  let checkoutRoot;
  const fixture = mergeIntentFixture({ onCheckout: (root) => { checkoutRoot = root; } });
  const { error } = await runPhaseFixture("execute", fixture);
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "fixture_stop");
  const checkout = fixture.calls.find(([name]) => name === "checkout");
  const regenerate = fixture.calls.find(([name]) => name === "regenerate");
  assert.deepEqual(checkout.slice(1), [fixture.state.baseSha, process.cwd()]);
  assert.equal(regenerate[1], checkoutRoot);
  assert.equal(regenerate[2], "0.5.0");
  const order = fixture.calls.map(([name]) => name);
  assert.equal(order.indexOf("jobs") < order.indexOf("checkout"), true);
  assert.equal(order.indexOf("regenerate") < order.indexOf("merge"), true);
  assert.equal(order.indexOf("regenerate") > order.indexOf("checks"), true);
  assert.deepEqual(
    fixture.calls.find(([name]) => name === "merge"),
    ["merge", 12, { merge_method: "squash", expected_head_sha: fixture.state.preparedCommitSha }],
  );
  await assert.rejects(() => fsp.access(checkoutRoot));
});

test("an altered candidate tree is refused by regeneration before merge", async () => {
  const fixture = mergeIntentFixture({
    regenerationAlter: (files) => files.map((file) => ({ ...file, content: `${file.content}tampered\n` })),
  });
  const { error } = await runPhaseFixture("execute", fixture);
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "candidate_regeneration_mismatch");
  assert.equal(fixture.calls.some(([name]) => ["merge", "updatePullRequest", "createRef"].includes(name)), false);
});

const REGENERATION_STUB_SOURCE = `
import { execFileSync } from "node:child_process";
import fsp from "node:fs/promises";
import path from "node:path";
const arguments_ = process.argv.slice(2);
const value = (name) => arguments_[arguments_.indexOf(name) + 1];
const root = path.resolve(value("--root"));
const observation = {
  root,
  headSha: execFileSync("git", ["-C", root, "rev-parse", "HEAD"], { encoding: "utf8" }).trim(),
  status: execFileSync("git", ["-C", root, "status", "--porcelain"], { encoding: "utf8" }).trim(),
  credentialsPresent: ["GITHUB_TOKEN", "GH_TOKEN", "RELEASE_APP_PRIVATE_KEY", "ACTIONS_RUNTIME_TOKEN"].filter((key) => process.env[key] !== undefined),
};
await fsp.writeFile(process.env.MF_STUB_OBSERVATION, JSON.stringify(observation));
const payload = JSON.parse(process.env.MF_STUB_RESULT);
for (const file of payload.files) {
  const target = path.join(root, file.path);
  await fsp.mkdir(path.dirname(target), { recursive: true });
  await fsp.writeFile(target, file.content);
}
await fsp.writeFile(value("--result"), JSON.stringify(payload.output));
`;

test("the default regeneration path runs the credential-free preparer in a clean base checkout", async () => {
  const { reproduceCandidateTree } = await import("./release-automation.mjs");
  const { execFile: execFileCallback } = await import("node:child_process");
  const execFile = (await import("node:util")).promisify(execFileCallback);
  const repoRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "release-regeneration-base-"));
  const workRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "release-regeneration-work-"));
  try {
    const gitIdentity = ["-c", "user.email=release@example.com", "-c", "user.name=Release Fixture"];
    await execFile("git", ["-c", "init.defaultBranch=main", "init", "-q"], { cwd: repoRoot });
    await fsp.writeFile(path.join(repoRoot, "VERSION"), "0.4.0\n", "utf8");
    await execFile("git", [...gitIdentity, "add", "VERSION"], { cwd: repoRoot });
    await execFile("git", [...gitIdentity, "commit", "-q", "-m", "base"], { cwd: repoRoot });
    const baseSha = (await execFile("git", ["rev-parse", "HEAD"], { cwd: repoRoot })).stdout.trim();

    const notes = "# Media Finder v0.5.0\n\nAutomatically generated from repository history. Not editorially reviewed.\n";
    const candidateFiles = [
      { path: "VERSION", mode: "100644", content: "0.5.0\n" },
      { path: "docs/releases/0.5.0.md", mode: "100644", content: notes },
    ];
    const snapshot = {
      throughSha: baseSha,
      commits: [{ sha: baseSha, url: `https://github.com/owner/media-finder/commit/${baseSha}` }],
    };
    const expectedTreeMap = Object.fromEntries(candidateFiles.map((file) => [file.path, {
      mode: file.mode,
      sha256: sha256(file.content),
    }]));
    const state = buildPreparationEvidence({
      repository: "owner/media-finder",
      repositoryId: REPOSITORY_ID,
      appId: 123,
      installationId: 456,
      operationId: "release-op-1",
      attempt: 1,
      trustedControllerSha: SHA,
      originRunId: 77,
      originRunAttempt: 1,
      baseSha,
      previousStableTag: "v0.4.0",
      previousStableSha: baseSha,
      version: "0.5.0",
      notesInputSnapshot: snapshot,
      candidateFiles,
      expectedTree: expectedTreeMap,
      candidateTreeSha256: preparationWorkingTreeDigest(candidateFiles),
      preparedCommitSha: "e".repeat(40),
      preparedTreeSha: "f".repeat(40),
    });

    const observationPath = path.join(workRoot, "observation.json");
    const stubPath = path.join(workRoot, "stub-preparer.mjs");
    await fsp.writeFile(stubPath, REGENERATION_STUB_SOURCE, "utf8");
    const environment = {
      ...process.env,
      MF_STUB_OBSERVATION: observationPath,
      MF_STUB_RESULT: JSON.stringify({
        files: candidateFiles,
        output: {
          schema_version: 1,
          version: "0.5.0",
          base_commit: baseSha,
          previous_stable_tag: "v0.4.0",
          previous_stable_sha: baseSha,
          snapshot_sha256: sha256(`${canonicalJson(snapshot)}\n`),
          base_tree_sha256: "0".repeat(64),
          candidate_tree_sha256: preparationWorkingTreeDigest(candidateFiles),
          notes_path: candidateFiles[1].path,
          changed_files: candidateFiles.map((file) => file.path),
          expected_tree: expectedTreeMap,
        },
      }),
      GITHUB_TOKEN: "must-not-reach-the-preparer",
      RELEASE_APP_PRIVATE_KEY: "must-not-reach-the-preparer",
    };

    const reproduced = await reproduceCandidateTree({
      state,
      cwd: repoRoot,
      scriptPath: stubPath,
      python: process.execPath,
      environment,
    });
    assert.equal(reproduced.candidateFiles.length, candidateFiles.length);
    const observation = JSON.parse(await fsp.readFile(observationPath, "utf8"));
    assert.notEqual(observation.root, repoRoot);
    assert.equal(observation.headSha, baseSha);
    assert.equal(observation.status, "");
    assert.deepEqual(observation.credentialsPresent, []);
    await assert.rejects(() => fsp.access(observation.root));

    await assert.rejects(
      () => reproduceCandidateTree({
        state: { ...state, candidateTreeSha256: "1".repeat(64) },
        cwd: repoRoot,
        scriptPath: stubPath,
        python: process.execPath,
        environment,
      }),
      (error) => error instanceof ReleaseAutomationError && error.code === "candidate_regeneration_mismatch",
    );
  } finally {
    await fsp.rm(repoRoot, { recursive: true, force: true });
    await fsp.rm(workRoot, { recursive: true, force: true });
  }
});

test("release history is captured completely or reports its bound", async () => {
  const commitEntry = (index) => {
    const commitSha = index.toString(16).padStart(40, "0");
    return { sha: commitSha, html_url: `https://github.com/owner/media-finder/commit/${commitSha}` };
  };
  const historyPage = (count, total, offset = 0) => ({
    total_commits: total,
    commits: Array.from({ length: count }, (_, index) => commitEntry(offset + index + 1)),
  });

  const complete = await preparationFixture({ omitSnapshot: true, historyPages: [historyPage(100, 150, 0), historyPage(50, 150, 100)] });
  try {
    const result = await runReleaseAutomation({ phase: "prepare", ...complete, cwd: complete.root });
    assert.equal(result.state.notesInputSnapshot.history.commits.length, 150);
    assert.deepEqual(
      complete.calls.filter(([name]) => name === "compare").map(([, , , options]) => options.page ?? 1),
      [1, 2],
    );
  } finally {
    await fsp.rm(complete.root, { recursive: true, force: true });
  }

  const bounded = await preparationFixture({ omitSnapshot: true, historyPages: [historyPage(100, 600, 0)] });
  try {
    await assert.rejects(
      () => runReleaseAutomation({ phase: "prepare", ...bounded, cwd: bounded.root }),
      (error) => error instanceof ReleaseAutomationError &&
        error.code === "history_bound_exceeded" &&
        error.details.bound === 500 &&
        error.details.total === 600,
    );
    assert.equal(bounded.calls.some(([name]) => ["createBlob", "createTree", "createCommit", "upload"].includes(name)), false);
  } finally {
    await fsp.rm(bounded.root, { recursive: true, force: true });
  }

  const inconsistent = await preparationFixture({ omitSnapshot: true, historyPages: [historyPage(100, 200, 0), historyPage(10, 200, 100)] });
  try {
    await assert.rejects(
      () => runReleaseAutomation({ phase: "prepare", ...inconsistent, cwd: inconsistent.root }),
      (error) => error instanceof ReleaseAutomationError && error.code === "history_incomplete",
    );
    assert.equal(inconsistent.calls.some(([name]) => name === "upload"), false);
  } finally {
    await fsp.rm(inconsistent.root, { recursive: true, force: true });
  }
});

function mutableAuthFixture({ slug = "media-finder-release", tokenPermissions = TOKEN_PERMISSIONS } = {}) {
  const calls = [];
  let now = Date.now();
  let permissions = tokenPermissions;
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).endsWith("/app")) return response(200, { id: 123, client_id: "Iv1.fixture", ...(slug === null ? {} : { slug }) });
    if (String(url).endsWith("/repos/owner/media-finder/installation")) return response(200, { id: 456, app_id: 123 });
    if (String(url).endsWith("/app/installations/456/access_tokens")) {
      return response(201, {
        token: "fixture-token",
        expires_at: new Date(now + 3600000).toISOString(),
        permissions,
      });
    }
    if (String(url).endsWith("/installation/repositories")) return response(200, { repositories: [{ id: REPOSITORY_ID, full_name: "owner/media-finder" }] });
    return response(404, { message: "not found" });
  };
  const authenticator = new GitHubAppAuthenticator({
    fetchImpl,
    appId: "Iv1.fixture",
    repository: "owner/media-finder",
    privateKey: PRIVATE_KEY,
    now: () => now,
  });
  return {
    calls,
    authenticator,
    advance(milliseconds) {
      now += milliseconds;
    },
    setTokenPermissions(value) {
      permissions = value;
    },
  };
}

test("App identity, repository scope and exact permissions are validated on every issuance", async () => {
  const fixture = mutableAuthFixture();
  const first = await fixture.authenticator.ensureToken();
  assert.equal(first.identity.appSlug, "media-finder-release");
  const issuanceCalls = fixture.calls.length;
  fixture.setTokenPermissions({ ...TOKEN_PERMISSIONS, administration: "write" });
  fixture.advance(56 * 60 * 1000);
  await assert.rejects(
    () => fixture.authenticator.ensureToken(),
    (error) => error instanceof ReleaseAutomationError && error.code === "token_scope_mismatch",
  );
  assert.equal(fixture.calls.length > issuanceCalls, true);

  const scopeFixture = mutableAuthFixture();
  await scopeFixture.authenticator.ensureToken();
  const scopeCalls = scopeFixture.calls.length;
  scopeFixture.setTokenPermissions(TOKEN_PERMISSIONS);
  scopeFixture.advance(56 * 60 * 1000);
  const renewed = await scopeFixture.authenticator.ensureToken();
  assert.equal(renewed.identity.repositoryId, REPOSITORY_ID);
  assert.equal(scopeFixture.calls.length > scopeCalls, true);
});

test("a release App without an authenticated bot identity fails closed", async () => {
  const fixture = mutableAuthFixture({ slug: null });
  await assert.rejects(
    () => fixture.authenticator.ensureToken(),
    (error) => error instanceof ReleaseAutomationError && error.code === "app_identity_mismatch",
  );
});

test("missing release credentials and unsafe inputs stop before any repository mutation", async () => {
  const state = executableEvidence({ pullRequest: true });
  const calls = [];
  const fixture = executionFixture({ state, calls, protection: protectionFixture() });

  await assert.rejects(
    () => runPhaseFixture("request", {
      api: fixture.api,
      auth: undefined,
      context: fixture.context,
      input: { version: "0.5.0" },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA, environment: {} },
      cwd: process.cwd(),
    }).then((outcome) => {
      if (outcome.error) throw outcome.error;
    }),
    (error) => error instanceof ReleaseAutomationError && error.code === "missing_credentials",
  );
  assert.deepEqual(calls, []);

  for (const version of ["0.5.0; rm -rf /", "0.5.0-rc.1", "$(id)", "0.5"]) {
    const unsafe = await runPhaseFixture("request", {
      ...fixture,
      input: { state, version },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    });
    assert.equal(unsafe.error instanceof ReleaseAutomationError, true, version);
    assert.equal(unsafe.error.code, "invalid_version", version);
  }
  assert.equal(calls.some(([name]) => ["merge", "createPullRequest", "createRef"].includes(name)), false);

  assert.throws(
    () => evidence({ candidateFiles: [{ path: "../escape", mode: "100644", content: "0.5.0\n" }] }),
    (error) => error instanceof ReleaseAutomationError && error.code === "candidate_path_invalid",
  );
});

test("a foreign repository or unauthorized actor cannot start a release request", async () => {
  const state = executableEvidence({ pullRequest: true });
  const calls = [];
  const fixture = executionFixture({ state, calls, protection: protectionFixture() });

  const foreign = await runPhaseFixture("request", {
    ...fixture,
    context: { ...fixture.context, repository: "evil/repo" },
    input: { state, version: "0.5.0" },
    config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
  });
  assert.equal(foreign.error instanceof ReleaseAutomationError, true);
  assert.equal(["repository_mismatch", "repository_scope_mismatch"].includes(foreign.error.code), true);

  const foreignCalls = calls.length;
  const stranger = await runPhaseFixture("request", {
    ...fixture,
    context: { ...fixture.context, actor: "stranger" },
    input: { state, version: "0.5.0" },
    config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
  });
  assert.equal(stranger.error instanceof ReleaseAutomationError, true);
  assert.equal(stranger.error.code, "unauthorized_actor");
  assert.equal(calls.length, foreignCalls);
  assert.equal(calls.some(([name]) => ["createRef", "createPullRequest", "merge"].includes(name)), false);
});

test("the CLI accepts the pinned request invocation and rejects unsafe arguments", async () => {
  const { execFile: execFileCallback } = await import("node:child_process");
  const { fileURLToPath } = await import("node:url");
  const execFile = (await import("node:util")).promisify(execFileCallback);
  const scriptPath = fileURLToPath(new URL("./release-automation.mjs", import.meta.url));
  const environment = { PATH: process.env.PATH, HOME: process.env.HOME };
  const run = async (arguments_) => {
    try {
      await execFile(process.execPath, [scriptPath, ...arguments_], { cwd: path.dirname(scriptPath), env: environment });
      return { code: 0, stderr: "" };
    } catch (error) {
      return { code: error.code, stderr: String(error.stderr ?? "") };
    }
  };

  const requested = await run(["--phase", "request", "--version", "0.5.0"]);
  assert.equal(requested.code, 1);
  assert.equal(requested.stderr.includes("untrusted_trigger"), true);
  assert.equal(requested.stderr.includes("phase_invalid"), false);
  assert.equal(requested.stderr.includes("unsafe_input"), false);

  const missingValue = await run(["--version"]);
  assert.equal(missingValue.code, 1);
  assert.equal(missingValue.stderr.includes("unsafe_input"), true);

  const positional = await run(["0.5.0"]);
  assert.equal(positional.code, 1);
  assert.equal(positional.stderr.includes("unsafe_input"), true);
});

test("a workflow run associated with a foreign pull request cannot satisfy release checks", () => {
  const run = restWorkflowRun();
  run.pull_requests[0].base.repo.id = REPOSITORY_ID + 1;
  const result = evaluateRequiredChecks(restCheckRuns(run), {
    headSha: SHA,
    baseSha: SHA,
    repository: "owner/media-finder",
    repositoryId: REPOSITORY_ID,
    workflowRuns: [run],
    workflowJobs: { total_count: 7, jobs: restJobs(run) },
  });
  assert.equal(result.state, "pending");
});

// ---------------------------------------------------------------------------
// Required-check gates, mandatory protection inspection and the protected
// expected-head squash merge (OpenSpec 2.3 and 2.4).
// ---------------------------------------------------------------------------

const GATE_OPTIONS = {
  headSha: SHA,
  baseSha: SHA,
  repository: "owner/media-finder",
  repositoryId: REPOSITORY_ID,
};

test("each of the seven required verification contexts gates the candidate independently", () => {
  assert.equal(REQUIRED_CHECK_CONTEXTS.length, 7);
  assert.equal(new Set(REQUIRED_CHECK_CONTEXTS).size, 7);
  const run = restWorkflowRun();
  const baseline = evaluateRequiredChecks(restCheckRuns(run), {
    ...GATE_OPTIONS,
    workflowRuns: [run],
    workflowJobs: { total_count: 7, jobs: restJobs(run) },
  });
  assert.equal(baseline.state, "passed");
  assert.deepEqual(Object.values(baseline.statuses), Array(7).fill("success"));

  for (const context of REQUIRED_CHECK_CONTEXTS) {
    for (const conclusion of ["failure", "cancelled", "skipped", "timed_out", "action_required", "neutral"]) {
      const statuses = { [context]: { conclusion } };
      const failed = evaluateRequiredChecks(restCheckRuns(run, statuses), {
        ...GATE_OPTIONS,
        workflowRuns: [run],
        workflowJobs: { total_count: 7, jobs: restJobs(run, statuses) },
      });
      assert.equal(failed.state, "failed", `${context} ${conclusion}`);
      assert.equal(failed.statuses[context], conclusion, `${context} ${conclusion}`);
      assert.equal(failed.failures.some((failure) => failure.context === context), true, `${context} ${conclusion}`);
    }

    const pendingStatuses = { [context]: { status: "in_progress" } };
    const pending = evaluateRequiredChecks(restCheckRuns(run, pendingStatuses), {
      ...GATE_OPTIONS,
      workflowRuns: [run],
      workflowJobs: { total_count: 7, jobs: restJobs(run, pendingStatuses) },
    });
    assert.equal(pending.state, "pending", context);
    assert.equal(pending.statuses[context], "pending", context);

    const missingChecks = restCheckRuns(run).filter((entry) => entry.name !== context);
    const missing = evaluateRequiredChecks(missingChecks, {
      ...GATE_OPTIONS,
      workflowRuns: [run],
      workflowJobs: { total_count: 7, jobs: restJobs(run) },
    });
    assert.equal(missing.state, "pending", context);
    assert.equal(missing.statuses[context], "missing", context);

    const missingJobs = restJobs(run).filter((entry) => entry.name !== context.split(" / ").at(-1));
    const jobMissing = evaluateRequiredChecks(restCheckRuns(run), {
      ...GATE_OPTIONS,
      workflowRuns: [run],
      workflowJobs: { total_count: missingJobs.length, jobs: missingJobs },
    });
    assert.equal(jobMissing.state, "pending", context);
    assert.equal(jobMissing.statuses[context], "missing", context);

    const staleJobs = restJobs({ ...run, head_sha: "b".repeat(40) }, {}, { includeAttempt: true });
    const stale = evaluateRequiredChecks(restCheckRuns(run), {
      ...GATE_OPTIONS,
      workflowRuns: [run],
      workflowJobs: { total_count: 7, jobs: staleJobs },
    });
    assert.equal(stale.state, "pending", context);
    assert.equal(stale.statuses[context], "stale", context);

    const untrustedChecks = restCheckRuns(run).map((entry) => entry.name === context ? { ...entry, app: { id: 999 } } : entry);
    assert.throws(
      () => evaluateRequiredChecks(untrustedChecks, {
        ...GATE_OPTIONS,
        workflowRuns: [run],
        workflowJobs: { total_count: 7, jobs: restJobs(run) },
      }),
      (error) => error instanceof ReleaseAutomationError && error.code === "untrusted_workflow",
      context,
    );
  }

  const failedRun = restWorkflowRun({ conclusion: "failure" });
  const workflowFailed = evaluateRequiredChecks(restCheckRuns(failedRun), {
    ...GATE_OPTIONS,
    workflowRuns: [failedRun],
    workflowJobs: { total_count: 7, jobs: restJobs(failedRun, {}, {}) },
  });
  assert.equal(workflowFailed.state, "failed");
  assert.equal(Object.keys(workflowFailed.statuses).length, 7);
});

test("a head or base change invalidates earlier check evidence", () => {
  const oldHead = "b".repeat(40);
  const oldRun = restWorkflowRun({ headSha: oldHead });
  const oldHeadResult = evaluateRequiredChecks(restCheckRuns(oldRun), {
    ...GATE_OPTIONS,
    workflowRuns: [oldRun],
    workflowJobs: { total_count: 7, jobs: restJobs(oldRun) },
  });
  assert.equal(oldHeadResult.state, "pending");
  assert.deepEqual(Object.values(oldHeadResult.statuses), Array(7).fill("missing"));

  const changedBase = restWorkflowRun({ baseSha: "c".repeat(40) });
  const baseResult = evaluateRequiredChecks(restCheckRuns(changedBase), {
    ...GATE_OPTIONS,
    workflowRuns: [changedBase],
    workflowJobs: { total_count: 7, jobs: restJobs(changedBase) },
  });
  assert.equal(baseResult.state, "pending");
  assert.deepEqual(Object.values(baseResult.statuses), Array(7).fill("missing"));

  const currentRun = restWorkflowRun();
  const oldJobs = restJobs(restWorkflowRun({ headSha: oldHead }));
  const staleJobs = evaluateRequiredChecks(restCheckRuns(currentRun), {
    ...GATE_OPTIONS,
    workflowRuns: [currentRun],
    workflowJobs: { total_count: 7, jobs: oldJobs },
  });
  assert.equal(staleJobs.state, "pending");
  assert.deepEqual(Object.values(staleJobs.statuses), Array(7).fill("stale"));

  const nameOnly = restCheckRuns(currentRun).map((entry) => ({ ...entry, name: entry.name.split(" / ").at(-1) }));
  const nameOnlyResult = evaluateRequiredChecks(nameOnly, {
    ...GATE_OPTIONS,
    workflowRuns: [currentRun],
    workflowJobs: { total_count: 7, jobs: restJobs(currentRun) },
  });
  assert.equal(nameOnlyResult.state, "pending");

  const foreignRun = restWorkflowRun();
  foreignRun.pull_requests[0].head.repo.id = REPOSITORY_ID + 1;
  const foreignResult = evaluateRequiredChecks(restCheckRuns(foreignRun), {
    ...GATE_OPTIONS,
    workflowRuns: [foreignRun],
    workflowJobs: { total_count: 7, jobs: restJobs(foreignRun) },
  });
  assert.equal(foreignResult.state, "pending");

  // A run for the same head that is not the trusted pull-request CI workflow is
  // never silently ignored: the gate stops with untrusted evidence.
  const untrustedEvent = restWorkflowRun({ event: "workflow_call", pullRequests: [] });
  assert.throws(
    () => evaluateRequiredChecks(restCheckRuns(untrustedEvent), {
      ...GATE_OPTIONS,
      workflowRuns: [untrustedEvent],
      workflowJobs: { total_count: 7, jobs: restJobs(untrustedEvent) },
    }),
    (error) => error instanceof ReleaseAutomationError && error.code === "untrusted_workflow",
  );
});

test("a narrowed required-check set cannot weaken the release gate", () => {
  const run = restWorkflowRun();
  const options = {
    ...GATE_OPTIONS,
    workflowRuns: [run],
    workflowJobs: { total_count: 7, jobs: restJobs(run) },
  };
  assert.equal(evaluateRequiredChecks(restCheckRuns(run), options).state, "passed");
  assert.equal(
    evaluateRequiredChecks(restCheckRuns(run), { ...options, requiredContexts: [...REQUIRED_CHECK_CONTEXTS] }).state,
    "passed",
  );
  for (const requiredContexts of [
    [],
    REQUIRED_CHECK_CONTEXTS.slice(0, 6),
    ["verification / unit"],
    [...REQUIRED_CHECK_CONTEXTS, "verification / extra"],
    [REQUIRED_CHECK_CONTEXTS[0], ...REQUIRED_CHECK_CONTEXTS.slice(0, 6)],
    REQUIRED_CHECK_CONTEXTS.map(() => REQUIRED_CHECK_CONTEXTS[0]),
  ]) {
    assert.throws(
      () => evaluateRequiredChecks(restCheckRuns(run), { ...options, requiredContexts }),
      (error) => error instanceof ReleaseAutomationError && error.code === "check_contexts_invalid",
      JSON.stringify(requiredContexts),
    );
  }
});

test("the approved protection baseline rejects every nested drift and malformed field", () => {
  const baseline = protectionFixture();
  assert.doesNotThrow(() => assertApprovedBranchProtection(baseline));

  const nested = [
    ["enforce_admins", true],
    ["required_linear_history", true],
    ["required_conversation_resolution", true],
    ["allow_force_pushes", false],
    ["allow_deletions", false],
  ];
  for (const [key, expected] of nested) {
    assert.throws(() => assertApprovedBranchProtection({ ...baseline, [key]: { enabled: !expected } }), (error) => error.code === "protection_changed", `${key} drift`);
    assert.throws(() => assertApprovedBranchProtection({ ...baseline, [key]: {} }), (error) => error.code === "protection_malformed", `${key} missing enabled`);
    assert.throws(() => assertApprovedBranchProtection({ ...baseline, [key]: { enabled: expected ? "true" : "false" } }), (error) => error.code === "protection_malformed", `${key} string enabled`);
    assert.throws(() => assertApprovedBranchProtection({ ...baseline, [key]: expected }), (error) => error.code === "protection_malformed", `${key} bare boolean`);
    assert.throws(() => assertApprovedBranchProtection({ ...baseline, [key]: [expected] }), (error) => error.code === "protection_malformed", `${key} array`);
  }

  const checks = baseline.required_status_checks.checks;
  const withChecks = (value) => ({ ...baseline, required_status_checks: { ...baseline.required_status_checks, ...value } });
  assert.throws(() => assertApprovedBranchProtection(withChecks({ strict: false })), (error) => error.code === "protection_changed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ strict: "true" })), (error) => error.code === "protection_malformed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ strict: undefined })), (error) => error.code === "protection_malformed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ checks: checks.slice(0, 6) })), (error) => error.code === "protection_changed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ checks: [...checks, { context: "verification / extra", app_id: GITHUB_ACTIONS_APP_ID }] })), (error) => error.code === "protection_changed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ checks: [checks[0], ...checks.slice(0, 6)] })), (error) => error.code === "protection_changed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ checks: checks.map((check, index) => index === 0 ? { ...check, app_id: 999 } : check) })), (error) => error.code === "protection_changed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ checks: checks.map((check, index) => index === 0 ? { ...check, app_id: undefined } : check) })), (error) => error.code === "protection_malformed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ checks: checks.map((check, index) => index === 0 ? { context: "", app_id: GITHUB_ACTIONS_APP_ID } : check) })), (error) => error.code === "protection_malformed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ contexts: checks.map((check, index) => index === 0 ? "verification / other" : check.context) })), (error) => error.code === "protection_changed");
  assert.throws(() => assertApprovedBranchProtection(withChecks({ contexts: checks.map((check) => check.context).slice(0, 6) })), (error) => error.code === "protection_changed");

  const withReviews = (value) => ({ ...baseline, required_pull_request_reviews: value });
  assert.throws(() => assertApprovedBranchProtection(withReviews({ ...baseline.required_pull_request_reviews, required_approving_review_count: 1 })), (error) => error.code === "protection_changed");
  assert.throws(() => assertApprovedBranchProtection(withReviews({ ...baseline.required_pull_request_reviews, require_code_owner_reviews: true })), (error) => error.code === "protection_changed");
  assert.throws(() => assertApprovedBranchProtection(withReviews({ ...baseline.required_pull_request_reviews, require_last_push_approval: true })), (error) => error.code === "protection_changed");
  assert.throws(() => assertApprovedBranchProtection(withReviews(undefined)), (error) => error.code === "protection_malformed");
  assert.throws(() => assertApprovedBranchProtection(withReviews({})), (error) => error.code === "protection_malformed");
  for (const key of ["users", "teams", "apps"]) {
    const allowances = { users: [], teams: [], apps: [], [key]: ["bypass"] };
    assert.throws(
      () => assertApprovedBranchProtection(withReviews({ ...baseline.required_pull_request_reviews, bypass_pull_request_allowances: allowances })),
      (error) => error.code === "protection_changed",
      key,
    );
    const incomplete = { users: [], teams: [], apps: [] };
    delete incomplete[key];
    assert.throws(
      () => assertApprovedBranchProtection(withReviews({ ...baseline.required_pull_request_reviews, bypass_pull_request_allowances: incomplete })),
      (error) => error.code === "protection_malformed",
      key,
    );
  }

  for (const malformed of [undefined, null, [], "baseline", 0, { required_status_checks: null }, { ...baseline, required_status_checks: undefined }]) {
    assert.throws(() => assertApprovedBranchProtection(malformed), (error) => error.code === "protection_malformed", JSON.stringify(malformed));
  }
});

test("main-branch protection is inspected before candidate exposure and immediately before merge", async () => {
  const fixture = mergeIntentFixture();
  const { error } = await runPhaseFixture("execute", fixture);
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "fixture_stop");

  const calls = fixture.calls;
  const names = calls.map(([name]) => name);
  const protections = names.map((name, index) => name === "protection" ? index : -1).filter((index) => index >= 0);
  assert.equal(protections.length, 2);
  const branchRef = calls.findIndex(([name, ref]) => name === "ref" && String(ref).startsWith("heads/release-"));
  assert.equal(branchRef > protections[0], true);
  assert.equal(protections[0] < names.indexOf("createPullRequest"), true);
  assert.equal(protections[1] > names.lastIndexOf("jobs"), true);
  assert.equal(protections[1] === names.indexOf("merge") - 1, true);

  const mutations = names.filter((name) => ["createRef", "createPullRequest", "merge", "updatePullRequest", "createRelease", "updateRelease"].includes(name));
  assert.deepEqual(mutations, ["createPullRequest", "merge"]);
});

test("a denied, missing or malformed protection read stops before candidate exposure", async () => {
  const cases = [
    { label: "denied", read: async () => { throw new ReleaseAutomationError("github_api_error", "Forbidden.", { status: 403 }); }, code: "github_api_error" },
    { label: "missing", read: async () => { throw new ReleaseAutomationError("github_api_error", "Branch not protected.", { status: 404 }); }, code: "github_api_error" },
    { label: "malformed", read: async () => ({}), code: "protection_malformed" },
    { label: "null", read: async () => null, code: "protection_malformed" },
    { label: "error envelope", read: async () => ({ message: "Not Found", documentation_url: "https://docs.github.com" }), code: "protection_malformed" },
  ];
  for (const { label, read, code } of cases) {
    const calls = [];
    const state = executableEvidence();
    const fixture = executionFixture({ state, calls, protection: protectionFixture() });
    fixture.api.getBranchProtection = async (...args) => {
      calls.push(["protection", ...args]);
      return read();
    };
    const { error } = await runPhaseFixture("execute", {
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, label);
    assert.equal(error.code, code, label);
    assert.equal(calls.some(([name]) => ["createRef", "createPullRequest", "merge"].includes(name)), false, label);
  }
});

test("missing protection-read endpoints stop before candidate exposure", async () => {
  for (const method of ["getBranchProtection", "getRepository"]) {
    const calls = [];
    const state = executableEvidence();
    const fixture = executionFixture({ state, calls, protection: protectionFixture() });
    delete fixture.api[method];
    const { error } = await runPhaseFixture("execute", {
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, method);
    assert.equal(error.code, "protection_evidence_unavailable", method);
    assert.equal(calls.some(([name]) => ["createRef", "createPullRequest", "merge"].includes(name)), false, method);
  }
});

test("a base change after the checks stops the merge without force-pushing", async () => {
  const calls = [];
  const state = executableEvidence({ pullRequest: true });
  const fixture = executionFixture({ state, calls, protection: protectionFixture() });
  const advancedMain = "9".repeat(40);
  fixture.api.getRef = async (...args) => {
    calls.push(["ref", ...args]);
    return { object: { sha: args[0] === "heads/main" ? advancedMain : state.preparedCommitSha } };
  };
  fixture.api.updatePullRequest = async (...args) => {
    calls.push(["updatePullRequest", ...args]);
    return { state: "closed" };
  };
  const checkpointUploads = [];
  fixture.artifacts = {
    async read() {
      return state;
    },
    async upload({ name, content, retentionDays, overwrite }) {
      checkpointUploads.push({ name, retentionDays, overwrite, checkpoint: JSON.parse(content) });
      return {
        id: 950,
        name,
        digest: `sha256:${DIGEST}`,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        expired: false,
        workflow_run: { id: 77, repository_id: REPOSITORY_ID, head_repository_id: REPOSITORY_ID, head_sha: SHA },
      };
    },
  };
  const { error } = await runPhaseFixture("execute", {
    ...fixture,
    input: { state },
    config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "base_changed");
  assert.equal(calls.some(([name]) => name === "merge"), false);
  assert.equal(calls.some(([name]) => name === "createRef"), false);
  assert.deepEqual(calls.find(([name]) => name === "updatePullRequest"), ["updatePullRequest", 12, { state: "closed" }]);
  assert.equal(checkpointUploads.length, 1);
  assert.equal(checkpointUploads[0].checkpoint.checkpointKind, "stale-base");
  assert.equal(checkpointUploads[0].checkpoint.disposition, "terminal_stale_base");
  assert.equal(checkpointUploads[0].checkpoint.currentMainSha, advancedMain);
});

test("a denied, missing or malformed protection read stops immediately before the merge", async () => {
  const cases = [
    { label: "denied", read: async () => { throw new ReleaseAutomationError("github_api_error", "Forbidden.", { status: 403 }); }, code: "github_api_error" },
    { label: "missing", read: async () => { throw new ReleaseAutomationError("github_api_error", "Branch not protected.", { status: 404 }); }, code: "github_api_error" },
    { label: "malformed", read: async () => ({}), code: "protection_malformed" },
    { label: "drifted", read: async () => protectionFixture({ required_conversation_resolution: { enabled: false } }), code: "protection_changed" },
  ];
  for (const { label, read, code } of cases) {
    const calls = [];
    const state = executableEvidence({ pullRequest: true });
    const fixture = executionFixture({ state, calls, protection: protectionFixture() });
    fixture.api.getBranchProtection = async (...args) => {
      calls.push(["protection", ...args]);
      return read();
    };
    const { error } = await runPhaseFixture("execute", {
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, label);
    assert.equal(error.code, code, label);
    assert.equal(calls.some(([name]) => ["merge", "updatePullRequest", "createRelease"].includes(name)), false, label);
  }
});

test("there is no protection bypass switch", async () => {
  const calls = [];
  const state = executableEvidence({ pullRequest: true });
  const fixture = executionFixture({
    state,
    calls,
    protection: protectionFixture({ allow_force_pushes: { enabled: true } }),
    mergeError: new ReleaseAutomationError("fixture_stop", "Stop at the protected merge."),
  });
  const { error } = await runPhaseFixture("execute", {
    ...fixture,
    input: { state },
    config: {
      allowedActors: ["maintainer"],
      trustedControllerSha: SHA,
      allowProtectionBypass: true,
      skipProtectionCheck: true,
      protectionBypass: true,
      disableProtectionInspection: true,
    },
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "protection_changed");
  assert.equal(calls.some(([name]) => name === "merge"), false);
});

test("unresolved conversations, review requests and changes-requested reviews block the merge", async () => {
  const cases = [
    { label: "unresolved conversation", patch: (fixture) => { fixture.api.listReviewThreads = async () => [{ isResolved: false }]; }, code: "unresolved_discussion" },
    { label: "legacy unresolved conversation", patch: (fixture) => { fixture.api.listReviewThreads = async () => [{ resolved: false }]; }, code: "unresolved_discussion" },
    { label: "review requested", patch: (fixture) => { fixture.api.listReviewRequests = async () => ({ users: [{ login: "reviewer" }], teams: [] }); }, code: "review_requested" },
    { label: "changes requested", patch: (fixture) => { fixture.api.listReviews = async () => [{ state: "CHANGES_REQUESTED" }]; }, code: "changes_requested" },
    { label: "candidate closed", patch: (fixture) => { fixture.api.getPullRequest = async () => ({ ...candidatePullRequest(), state: "closed" }); }, code: "candidate_closed" },
    { label: "missing discussion evidence", patch: (fixture) => { delete fixture.api.listReviewThreads; }, code: "review_threads_unavailable" },
    { label: "missing review evidence", patch: (fixture) => { delete fixture.api.listReviews; }, code: "reviews_unavailable" },
    { label: "missing review-request evidence", patch: (fixture) => { delete fixture.api.listReviewRequests; }, code: "review_requests_unavailable" },
  ];
  for (const { label, patch, code } of cases) {
    const calls = [];
    const state = executableEvidence({ pullRequest: true });
    const fixture = executionFixture({
      state,
      calls,
      protection: protectionFixture(),
      mergeError: new ReleaseAutomationError("fixture_stop", "Stop at the protected merge."),
    });
    patch(fixture);
    const { error } = await runPhaseFixture("execute", {
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, label);
    assert.equal(error.code, code, label);
    assert.equal(calls.some(([name]) => name === "merge"), false, label);
  }
});

function candidatePullRequest() {
  return {
    number: 12,
    state: "open",
    head: { sha: "e".repeat(40), ref: "release-op-1-v0.5.0-attempt-1", repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
    base: { ref: "main", sha: SHA, repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
    user: { login: "media-finder-release[bot]", type: "Bot" },
  };
}

test("candidate gates are revalidated immediately before the protected merge", async () => {
  const cases = [
    {
      label: "conversation opened during checks",
      patch: (fixture) => {
        let reads = 0;
        fixture.api.listReviewThreads = async () => {
          reads += 1;
          return reads === 1 ? [] : [{ isResolved: false }];
        };
      },
      code: "unresolved_discussion",
    },
    {
      label: "changes requested during checks",
      patch: (fixture) => {
        let reads = 0;
        fixture.api.listReviews = async () => {
          reads += 1;
          return reads === 1 ? [] : [{ state: "CHANGES_REQUESTED" }];
        };
      },
      code: "changes_requested",
    },
    {
      label: "review requested during checks",
      patch: (fixture) => {
        let reads = 0;
        fixture.api.listReviewRequests = async () => {
          reads += 1;
          return reads === 1 ? { users: [], teams: [] } : { users: [{ login: "reviewer" }], teams: [] };
        };
      },
      code: "review_requested",
    },
    {
      label: "head replaced during checks",
      patch: (fixture) => {
        let reads = 0;
        fixture.api.getPullRequest = async () => {
          reads += 1;
          const pullRequest = candidatePullRequest();
          if (reads >= 2) pullRequest.head.sha = "d".repeat(40);
          return pullRequest;
        };
      },
      code: "candidate_identity_mismatch",
    },
    {
      label: "candidate closed during checks",
      patch: (fixture) => {
        let reads = 0;
        fixture.api.getPullRequest = async () => {
          reads += 1;
          const pullRequest = candidatePullRequest();
          if (reads >= 2) pullRequest.state = "closed";
          return pullRequest;
        };
      },
      code: "candidate_closed",
    },
  ];
  for (const { label, patch, code } of cases) {
    const calls = [];
    const state = executableEvidence({ pullRequest: true });
    const fixture = executionFixture({
      state,
      calls,
      protection: protectionFixture(),
      mergeError: new ReleaseAutomationError("fixture_stop", "Stop at the protected merge."),
    });
    patch(fixture);
    const { error } = await runPhaseFixture("execute", {
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, label);
    assert.equal(error.code, code, label);
    assert.equal(calls.some(([name]) => name === "merge"), false, label);
  }

  const mergedCalls = [];
  const mergedState = executableEvidence({ pullRequest: true });
  const mergedFixture = executionFixture({
    state: mergedState,
    calls: mergedCalls,
    protection: protectionFixture(),
    mergeError: new ReleaseAutomationError("fixture_stop", "Stop at the protected merge."),
  });
  let mergedReads = 0;
  mergedFixture.api.getPullRequest = async () => {
    mergedReads += 1;
    const pullRequest = candidatePullRequest();
    if (mergedReads >= 2) {
      pullRequest.state = "closed";
      pullRequest.merged = true;
      pullRequest.merged_at = "2026-01-02T00:00:00Z";
      pullRequest.merge_commit_sha = SHA;
    }
    return pullRequest;
  };
  // The reconciled merge commit is verified like any other merge result; the
  // fixture stops at main-publication polling because no push run exists.
  mergedFixture.api.getCommit = async (shaValue) => ({ tree: { sha: "f".repeat(40) }, parents: [{ sha: mergedState.baseSha }] });
  const merged = await runPhaseFixture("execute", {
    ...mergedFixture,
    input: { state: mergedState },
    config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
  });
  assert.equal(mergedCalls.some(([name]) => name === "merge"), false);
  assert.equal(merged.error instanceof ReleaseAutomationError, true);
  assert.equal(["timeout", "main_edge_not_verified"].includes(merged.error.code), true);
});

test("the protected squash merge carries only the expected head identity", async () => {
  const calls = [];
  const api = new GitHubRestApi({
    repository: "owner/media-finder",
    auth: {
      async request(method, endpoint, body) {
        calls.push({ method, endpoint, body });
        return { merged: true, sha: SHA, merge_commit_sha: SHA };
      },
    },
  });
  await api.mergePullRequest(12, { merge_method: "squash", expected_head_sha: SHA });
  assert.deepEqual(calls, [{
    method: "PUT",
    endpoint: "/repos/owner/media-finder/pulls/12/merge",
    body: { merge_method: "squash", sha: SHA },
  }]);

  for (const field of ["admin", "bypass", "bypass_pull_request_allowances", "dismiss_stale_reviews", "commit_title", "force"]) {
    assert.throws(
      () => api.mergePullRequest(12, { merge_method: "squash", expected_head_sha: SHA, [field]: true }),
      (error) => error instanceof ReleaseAutomationError && error.code === "merge_policy_violation",
      field,
    );
  }
  assert.throws(
    () => api.mergePullRequest(12, { merge_method: "merge", expected_head_sha: SHA }),
    (error) => error.code === "merge_policy_violation",
  );
  assert.throws(
    () => api.mergePullRequest(12, { merge_method: "squash" }),
    (error) => error.code === "merge_identity_missing",
  );
});

test("the controller never mutates repository settings or resolves conversations", () => {
  const methods = new Set(Object.getOwnPropertyNames(GitHubRestApi.prototype));
  for (const forbidden of [
    "updateBranchProtection",
    "deleteBranchProtection",
    "updateRepository",
    "updateBranchProtectionEnforcement",
    "resolveReviewThread",
    "unresolveReviewThread",
    "dismissReview",
    "submitReview",
    "approvePullRequest",
    "requestReviewers",
    "deleteReviewRequest",
  ]) {
    assert.equal(methods.has(forbidden), false, forbidden);
  }
});

test("a rejected or unconfirmed protected merge never reports success", async () => {
  const cases = [
    {
      label: "provider did not merge",
      merge: async () => ({ merged: false, message: "Head branch was modified. Review and try again." }),
      code: "merge_rejected",
    },
    {
      label: "conflict",
      merge: async () => { throw new ReleaseAutomationError("github_api_error", "Conflict.", { status: 409 }); },
      code: "github_api_error",
    },
    {
      label: "unprocessable",
      merge: async () => { throw new ReleaseAutomationError("github_api_error", "Head branch was modified.", { status: 422 }); },
      code: "github_api_error",
    },
  ];
  for (const { label, merge, code } of cases) {
    const calls = [];
    const state = executableEvidence({ pullRequest: true });
    const fixture = executionFixture({ state, calls, protection: protectionFixture() });
    fixture.api.mergePullRequest = async (...args) => {
      calls.push(["merge", ...args]);
      return merge();
    };
    const { error } = await runPhaseFixture("execute", {
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, label);
    assert.equal(error.code, code, label);
    const mergeIndex = calls.findIndex(([name]) => name === "merge");
    assert.equal(mergeIndex >= 0, true, label);
    assert.deepEqual(calls[mergeIndex][1], 12, label);
    assert.deepEqual(calls[mergeIndex][2], { merge_method: "squash", expected_head_sha: state.preparedCommitSha }, label);
    assert.equal(calls.slice(mergeIndex + 1).length, 0, label);
  }
});

test("an ordinary pull request cannot enter the generated-release exemption", async () => {
  const identityCases = [
    { label: "wrong author", patch: (pr) => { pr.user = { login: "outsider", type: "User" }; return pr; } },
    { label: "forged branch", patch: (pr) => { pr.head.ref = "release-forged-v0.5.0-attempt-1"; return pr; } },
    { label: "label-only claim", patch: (pr) => { pr.labels = [{ name: "release" }]; pr.user = { login: "outsider[bot]", type: "Bot" }; return pr; } },
    { label: "wrong base", patch: (pr) => { pr.base.ref = "develop"; return pr; } },
  ];
  for (const { label, patch } of identityCases) {
    const calls = [];
    const state = executableEvidence({ pullRequest: true });
    const fixture = executionFixture({ state, calls, protection: protectionFixture(), pullRequestPatch: patch });
    const { error } = await runPhaseFixture("execute", {
      ...fixture,
      input: { state },
      config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, label);
    assert.equal(error.code, "candidate_identity_mismatch", label);
    assert.equal(calls.some(([name]) => ["merge", "createPullRequest", "createRef"].includes(name)), false, label);
  }

  const fixture = executionIntentFixture({ branchMode: "matching" });
  fixture.api.getTree = async () => ({
    truncated: false,
    tree: [{ path: "VERSION", mode: "100644", type: "blob", sha: sha256("9.9.9\n") }],
  });
  fixture.api.getBlob = async () => ({ encoding: "base64", content: Buffer.from("9.9.9\n").toString("base64") });
  const altered = await runPhaseFixture("execute", fixture);
  assert.equal(altered.error instanceof ReleaseAutomationError, true);
  assert.equal(altered.error.code, "candidate_tree_mismatch");
  assert.equal(fixture.calls.some(([name]) => ["createRef", "createPullRequest", "merge"].includes(name)), false);
});

// ---------------------------------------------------------------------------
// Serialized requests, one operation-wide deadline, same-version reconciliation
// and bounded stale-candidate replacement (OpenSpec 2.5).
// ---------------------------------------------------------------------------

function steppingClock(stepMs = 1000) {
  let current = 0;
  return {
    now: () => {
      current += stepMs;
      return current;
    },
    sleep: async () => {},
  };
}

async function runReleaseAttempt(phase, options) {
  try {
    const result = await runReleaseAutomation({ phase, ...options });
    return { result };
  } catch (error) {
    return { error };
  }
}

function keepChecksPending(api, calls) {
  api.getCheckRuns = async (...args) => {
    calls.push(["checks", ...args]);
    return { check_runs: [] };
  };
}

function provideGreenChecks(api, calls, { headSha, baseSha, runId = 700 }) {
  const run = restWorkflowRun({ id: runId, runAttempt: 1, headSha, baseSha });
  api.getCheckRuns = async (...args) => {
    calls.push(["checks", ...args]);
    return { check_runs: restCheckRuns(run) };
  };
  api.getWorkflowRuns = async (input) => {
    calls.push(["runs", input]);
    if (input.event === "pull_request") return { total_count: 1, workflow_runs: [run] };
    return { workflow_runs: [] };
  };
  api.getWorkflowRunJobs = async (...args) => {
    calls.push(["jobs", ...args]);
    return { total_count: 7, jobs: restJobs(run) };
  };
}

test("one operation-wide deadline bounds the wait and reports the completed boundary", async () => {
  const state = executableEvidence({ pullRequest: true });
  const calls = [];
  const fixture = executionFixture({
    state,
    calls,
    protection: protectionFixture(),
    mergeError: new ReleaseAutomationError("fixture_stop", "Stop at the protected merge."),
  });
  keepChecksPending(fixture.api, calls);
  const { error } = await runReleaseAttempt("execute", {
    ...fixture,
    input: { state },
    config: { allowedActors: ["maintainer"], trustedControllerSha: SHA, operationDeadlineMs: 60_000 },
    clock: steppingClock(1000),
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "operation_deadline_exceeded");
  assert.equal(error.details.deadlineMs, 60_000);
  assert.equal(error.details.completedBoundary.operationId, "release-op-1");
  assert.equal(error.details.completedBoundary.attempt, 1);
  assert.equal(error.details.completedBoundary.prNumber, 12);
  assert.equal(error.details.completedBoundary.status, "authorized");
  assert.equal(typeof error.details.completedBoundary.deadlineAt, "string");
  assert.equal(calls.some(([name]) => name === "merge"), false);
  assert.equal(DEFAULT_OPERATION_DEADLINE_MS < 330 * 60 * 1000, true);
});

test("an operation deadline above the hosted job limit is refused", async () => {
  const state = executableEvidence({ pullRequest: true });
  const calls = [];
  const fixture = executionFixture({
    state,
    calls,
    protection: protectionFixture(),
    mergeError: new ReleaseAutomationError("fixture_stop", "Stop at the protected merge."),
  });
  const { error } = await runReleaseAttempt("execute", {
    ...fixture,
    input: { state },
    config: {
      allowedActors: ["maintainer"],
      trustedControllerSha: SHA,
      operationDeadlineMs: 6 * 60 * 60 * 1000,
    },
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "operation_deadline_invalid");
  assert.equal(error.details.bound, DEFAULT_OPERATION_DEADLINE_MS);
  assert.equal(calls.some(([name]) => ["createRef", "createPullRequest", "merge"].includes(name)), false);
});

test("a deadline expiry retains resumable state and a re-dispatch resumes the same operation", async () => {
  const state = executableEvidence({ pullRequest: true });
  const calls = [];
  const fixture = executionFixture({
    state,
    calls,
    protection: protectionFixture(),
    mergeError: new ReleaseAutomationError("fixture_stop", "Stop at the protected merge."),
  });
  keepChecksPending(fixture.api, calls);
  const config = { allowedActors: ["maintainer"], trustedControllerSha: SHA, operationDeadlineMs: 60_000 };
  const first = await runReleaseAttempt("request", {
    ...fixture,
    input: { state, version: "0.5.0" },
    config,
    clock: steppingClock(1000),
  });
  assert.equal(first.error instanceof ReleaseAutomationError, true);
  assert.equal(first.error.code, "operation_deadline_exceeded");
  assert.equal(first.error.details.completedBoundary.prNumber, 12);

  const checksBefore = calls.filter(([name]) => name === "checks").length;
  provideGreenChecks(fixture.api, calls, { headSha: state.preparedCommitSha, baseSha: state.baseSha });
  const second = await runReleaseAttempt("request", {
    ...fixture,
    input: { state, version: "0.5.0" },
    config,
    clock: { now: () => Date.now(), sleep: async () => {} },
  });
  assert.equal(second.error instanceof ReleaseAutomationError, true);
  assert.equal(second.error.code, "fixture_stop");
  assert.equal(calls.filter(([name]) => name === "checks").length > checksBefore, true);
  assert.equal(calls.filter(([name]) => name === "merge").length, 1);
  assert.equal(calls.some(([name]) => ["createBlob", "createTree", "createCommit", "upload"].includes(name)), false);
});

test("the operation deadline also bounds preparation", async () => {
  const fixture = await preparationFixture();
  const { error } = await runReleaseAttempt("prepare", {
    ...fixture,
    cwd: fixture.root,
    config: { ...fixture.config, operationDeadlineMs: 500 },
    clock: steppingClock(1000),
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "operation_deadline_exceeded");
  assert.equal(String(error.details.label).includes("preparation"), true);
  assert.equal(fixture.calls.some(([name]) => ["createBlob", "createTree", "createCommit", "upload"].includes(name)), false);
});

test("a second active release version is rejected before preparation", async () => {
  const fixture = await preparationFixture();
  fixture.api.listPullRequests = async (...args) => {
    fixture.calls.push(["pulls", ...args]);
    return [{ number: 20, head: { ref: "release-other-v0.6.0-attempt-1" } }];
  };
  const { error } = await runReleaseAttempt("request", { ...fixture, cwd: fixture.root });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "concurrent_release");
  assert.equal(error.details.version, "0.5.0");
  assert.equal(error.details.active.some((entry) => entry.ref === "release-other-v0.6.0-attempt-1"), true);
  assert.equal(fixture.calls.some(([name]) => ["createBlob", "createTree", "createCommit", "upload"].includes(name)), false);
});

test("the durable three-attempt limit survives reruns and stops with base_changed_repeatedly", async () => {
  const bases = ["a".repeat(40), "b".repeat(40), "c".repeat(40)];
  const advancedMain = "d".repeat(40);
  const runs = bases.map((_, index) => preparationDiscoveryRun({ id: 80 + index, runAttempt: 1, headSha: `${index + 1}`.repeat(40) }));
  const artifactLists = {};
  const metadataById = {};
  const payloadById = {};
  const originAttempts = {};
  runs.forEach((run, index) => {
    const attempt = index + 1;
    const artifactId = 900 + attempt;
    artifactLists[run.id] = [{ id: artifactId, name: `release-op-1-preparation-attempt-${attempt}` }];
    metadataById[artifactId] = {
      id: artifactId,
      name: `release-op-1-preparation-attempt-${attempt}`,
      digest: `sha256:${DIGEST}`,
      expires_at: new Date(Date.now() + 3600000).toISOString(),
      expired: false,
      workflow_run: {
        id: run.id,
        run_attempt: 1,
        repository_id: REPOSITORY_ID,
        head_repository_id: REPOSITORY_ID,
        head_sha: run.head_sha,
      },
    };
    payloadById[artifactId] = recoveryPayload(executableEvidence(), {
      attempt,
      baseSha: bases[index],
      trustedControllerSha: run.head_sha,
      originRunId: run.id,
      originRunAttempt: 1,
      preparedCommitSha: String(attempt).repeat(40),
    });
    originAttempts[`${run.id}:1`] = run;
  });
  const { fixture, error } = await runRecoveryFixture({
    phase: "request",
    currentSha: advancedMain,
    listedRuns: runs,
    artifactLists,
    metadataById,
    payloadById,
    originAttempts,
    patchApi(api) {
      api.getRef = async () => ({ object: { sha: advancedMain } });
    },
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "base_changed_repeatedly");
  assert.deepEqual(error.details.attempts, [1, 2, 3]);
  assert.equal(error.details.bound, 3);
  assert.equal(fixture.calls.some(([name]) => ["createBlob", "createTree", "createCommit", "upload"].includes(name)), false);
});

function checkpointPayload({
  kind = "pr-created",
  attempt = 1,
  operationId = "release-op-1",
  repository = "owner/media-finder",
  preparationArtifactId = 901,
  preparationArtifactDigest = DIGEST,
  producerRunId = 205,
  producerRunAttempt = 1,
  producerControllerSha = "c".repeat(40),
  trustedControllerSha = SHA,
  expiresAt,
  ...fields
} = {}) {
  const value = {
    schemaVersion: 1,
    evidenceKind: "release-checkpoint",
    checkpointKind: kind,
    repository,
    operationId,
    attempt,
    preparationArtifactId,
    preparationArtifactDigest,
    trustedControllerSha,
    producerRunId,
    producerRunAttempt,
    producerControllerSha,
    createdAt: "2026-01-01T00:00:00.000Z",
    ...(expiresAt === undefined ? {} : { expiresAt }),
    ...(kind === "pr-created" ? { prNumber: 12, prHeadSha: "1".repeat(40), prBaseSha: SHA } : {}),
    ...(kind === "stale-base" ? { prNumber: 12, prHeadSha: "1".repeat(40), prBaseSha: SHA, disposition: "terminal_stale_base", currentMainSha: "c".repeat(40) } : {}),
    ...(kind === "merged" ? { prNumber: 12, prHeadSha: "1".repeat(40), prBaseSha: SHA, mergedSha: "1".repeat(40) } : {}),
    ...fields,
  };
  return { ...value, contentDigest: sha256(canonicalJson(value)) };
}

function redigestCheckpoint(value) {
  const content = { ...value };
  delete content.contentDigest;
  delete content.artifact;
  return { ...content, contentDigest: sha256(canonicalJson(content)) };
}

async function staleReplacementFixture({ pullRequestPatch, checkpoints = [] } = {}) {
  const fixture = await preparationFixture({ omitSnapshot: true });
  const { root, calls, api, candidateFiles, baseTreeSha256, candidateTreeSha256, expectedTree } = fixture;
  const operationId = "release-op-1";
  const previousHead = "1".repeat(40);
  const previousBase = SHA;
  const currentMain = "c".repeat(40);
  const previousRunId = 77;
  const currentRunId = 205;
  const replacementHead = "2".repeat(40);
  const replacementTree = "3".repeat(40);
  const previousBranch = `${operationId}-v0.5.0-attempt-1`;
  const replacementBranch = `${operationId}-v0.5.0-attempt-2`;
  const future = () => new Date(Date.now() + 3600000).toISOString();
  const attemptOne = {
    number: 12,
    state: "open",
    head: { sha: previousHead, ref: previousBranch, repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
    base: { ref: "main", sha: currentMain, repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
    user: { login: "media-finder-release[bot]", type: "Bot" },
  };
  pullRequestPatch?.(attemptOne);
  const runObject = (id, headSha) => ({
    id,
    run_attempt: 1,
    status: "completed",
    conclusion: "success",
    event: "workflow_dispatch",
    path: "owner/media-finder/.github/workflows/prepare-release.yaml@main",
    head_sha: headSha,
    head_branch: "main",
    actor: { login: "maintainer", type: "User" },
    repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
    head_repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
    repository_id: REPOSITORY_ID,
    head_repository_id: REPOSITORY_ID,
  });
  const previousRun = runObject(previousRunId, previousHead);
  const currentRun = runObject(currentRunId, currentMain);
  const previousPayload = (() => {
    const value = evidence({
      operationId,
      attempt: 1,
      baseSha: previousBase,
      trustedControllerSha: previousHead,
      originRunId: previousRunId,
      originRunAttempt: 1,
      preparedCommitSha: previousHead,
      preparedTreeSha: PREPARATION_TREE_SHA,
    });
    delete value.contentDigest;
    const digestInput = { ...value };
    delete digestInput.artifact;
    value.contentDigest = sha256(canonicalJson(digestInput));
    value.artifact = {
      id: 901,
      digest: DIGEST,
      name: `${operationId}-preparation-attempt-1`,
      expiresAt: future(),
      retentionDaysRequested: 90,
      workflowRunId: previousRunId,
    };
    return value;
  })();
  const pullRequestsByNumber = { 12: attemptOne };
  const metadataById = {
    901: {
      id: 901,
      name: `${operationId}-preparation-attempt-1`,
      digest: `sha256:${DIGEST}`,
      expires_at: future(),
      expired: false,
      workflow_run: {
        id: previousRunId,
        run_attempt: 1,
        repository_id: REPOSITORY_ID,
        head_repository_id: REPOSITORY_ID,
        head_sha: previousHead,
      },
    },
  };
  const payloadById = { 901: previousPayload };
  const uploads = [];
  let nextArtifactId = 910;
  const uploadedNames = new Set();
  const extraRuns = new Map();
  const checkpointHints = new Map([[previousRunId, []], [currentRunId, []]]);
  for (const [index, entry] of checkpoints.entries()) {
    const attempt = entry.attempt ?? 1;
    const artifactId = entry.id ?? 960 + index;
    const producerRunId = entry.producerRunId ?? currentRunId;
    const producerRunAttempt = entry.producerRunAttempt ?? 1;
    const producerControllerSha = entry.producerControllerSha ?? currentMain;
    // An artifact is always listed under the run that produced it.
    const listingRunId = entry.listedInRunId ?? producerRunId;
    const name = entry.name ?? `${operationId}-${entry.kind}-attempt-${attempt}`;
    const record = checkpointPayload({
      kind: entry.kind,
      attempt,
      producerRunId,
      producerRunAttempt,
      producerControllerSha,
      preparationArtifactId: 901,
      preparationArtifactDigest: DIGEST,
      ...(entry.fields ?? {}),
    });
    metadataById[artifactId] = {
      id: artifactId,
      name,
      digest: `sha256:${entry.digest ?? DIGEST}`,
      expires_at: entry.expiresAt ?? future(),
      expired: entry.expired === true,
      workflow_run: {
        id: producerRunId,
        run_attempt: producerRunAttempt,
        repository_id: REPOSITORY_ID,
        head_repository_id: REPOSITORY_ID,
        head_sha: producerControllerSha,
      },
    };
    payloadById[artifactId] = entry.payload ?? record;
    if (entry.untrustedProducer !== undefined) extraRuns.set(`${producerRunId}:${producerRunAttempt}`, entry.untrustedProducer);
    checkpointHints.set(listingRunId, [...(checkpointHints.get(listingRunId) ?? []), { id: artifactId, name }]);
  }
  fixture.artifacts = {
    async read(id) {
      calls.push(["read", id]);
      return payloadById[id];
    },
    async upload({ name, content }) {
      calls.push(["upload", name]);
      if (uploadedNames.has(name)) throw new ReleaseAutomationError("artifact_upload_failed", "An artifact with this name already exists.");
      uploadedNames.add(name);
      const id = nextArtifactId;
      nextArtifactId += 1;
      const payload = JSON.parse(content);
      uploads.push({ id, name, payload });
      if (payload.checkpointKind !== undefined) {
        // The executing run uploads the checkpoint, so the provider metadata
        // reports that producing run (not the preparation's origin run).
        return {
          id,
          name,
          digest: `sha256:${DIGEST}`,
          expires_at: future(),
          expired: false,
          workflow_run: {
            id: currentRunId,
            run_attempt: 1,
            repository_id: REPOSITORY_ID,
            head_repository_id: REPOSITORY_ID,
            head_sha: currentMain,
          },
        };
      }
      payloadById[id] = payload;
      const metadata = {
        id,
        name,
        digest: `sha256:${DIGEST}`,
        expires_at: future(),
        expired: false,
        workflow_run: {
          id: currentRunId,
          run_attempt: 1,
          repository_id: REPOSITORY_ID,
          head_repository_id: REPOSITORY_ID,
          head_sha: currentMain,
        },
      };
      metadataById[id] = metadata;
      return metadata;
    },
  };

  const blobSha = (content) => sha256(content).slice(0, 40);
  const attemptOneFiles = previousPayload.candidateFiles;
  const attemptOneEntries = attemptOneFiles.map((file) => ({
    path: file.path,
    mode: file.mode,
    type: "blob",
    sha: blobSha(file.content),
  }));
  const contentByDigest = new Map([...candidateFiles, ...attemptOneFiles].map((file) => [blobSha(file.content), file.content]));
  const candidateTreeEntries = candidateFiles.map((file) => ({
    path: file.path,
    mode: file.mode,
    type: "blob",
    sha: blobSha(file.content),
  }));
  let checkProbes = 0;
  const prRun = (headSha) => restWorkflowRun({ id: 700, runAttempt: 1, headSha, baseSha: currentMain });

  api.getCollaboratorPermission = async () => ({ permission: "push" });
  api.getRepository = async () => ({
    id: REPOSITORY_ID,
    full_name: "owner/media-finder",
    owner: { type: "User", login: "owner" },
  });
  api.getWorkflowRuns = async (input) => {
    calls.push(["runs", input]);
    if (input.event === "workflow_dispatch") {
      const runs = [previousRun, currentRun, ...extraRuns.values()].filter((run, index, all) =>
        all.findIndex((candidate) => candidate.id === run.id) === index);
      return { total_count: runs.length, workflow_runs: runs };
    }
    if (input.event === "pull_request") return { total_count: 1, workflow_runs: [prRun(replacementHead)] };
    return { workflow_runs: [] };
  };
  api.getWorkflowRunAttempt = async (runId, attempt) => {
    calls.push(["origin-run", runId, attempt]);
    if (extraRuns.has(`${Number(runId)}:${Number(attempt)}`)) return extraRuns.get(`${Number(runId)}:${Number(attempt)}`);
    if (Number(runId) === previousRunId && Number(attempt) === 1) return previousRun;
    if (Number(runId) === currentRunId && Number(attempt) === 1) return currentRun;
    throw new Error(`unexpected origin attempt ${runId}:${attempt}`);
  };
  api.listRunArtifacts = async (runId) => {
    calls.push(["run-artifacts", runId]);
    const listed = [];
    if (Number(runId) === previousRunId) listed.push({ id: 901, name: `${operationId}-preparation-attempt-1` });
    listed.push(...(checkpointHints.get(Number(runId)) ?? []));
    return { total_count: listed.length, artifacts: listed };
  };
  api.getArtifact = async (artifactId) => {
    calls.push(["artifact", artifactId]);
    return metadataById[artifactId];
  };
  api.listPullRequests = async (input) => {
    calls.push(["pulls", input]);
    const live = Object.values(pullRequestsByNumber);
    const selected = input?.state === "open" ? live.filter((pullRequest) => pullRequest.state === "open") : live;
    return selected.map((pullRequest) => ({ number: pullRequest.number, head: { ref: pullRequest.head.ref } }));
  };
  api.getPullRequest = async (number) => {
    calls.push(["pr", number]);
    return { ...pullRequestsByNumber[Number(number)] };
  };
  api.updatePullRequest = async (number, body) => {
    calls.push(["updatePullRequest", number, body]);
    const pullRequest = pullRequestsByNumber[Number(number)];
    if (pullRequest !== undefined && body?.state === "closed") pullRequest.state = "closed";
    return { ...pullRequest };
  };
  api.getRef = async (ref) => {
    calls.push(["ref", ref]);
    if (ref === "heads/main") return { object: { sha: currentMain } };
    if (ref === `heads/${replacementBranch}`) {
      throw new ReleaseAutomationError("github_api_error", "Not found.", { status: 404 });
    }
    return { object: { sha: replacementHead } };
  };
  api.getCommit = async (sha) => {
    calls.push(["commit", sha]);
    if (sha === replacementHead) return { tree: { sha: replacementTree }, parents: [{ sha: currentMain }] };
    // The recorded attempt-1 prepared commit keeps its own tree and base.
    if (sha === previousHead) return { tree: { sha: PREPARATION_TREE_SHA }, parents: [{ sha: previousBase }] };
    return { tree: { sha: PREPARATION_BASE_TREE_SHA }, parents: [{ sha: currentMain }] };
  };
  api.getTree = async (sha) => {
    calls.push(["tree", sha]);
    // The recorded attempt-1 commit has its own recorded tree; the replacement
    // candidate has the freshly prepared one.
    if (sha === PREPARATION_TREE_SHA) return { truncated: false, tree: attemptOneEntries };
    return { truncated: false, tree: candidateTreeEntries };
  };
  api.getBlob = async (sha) => {
    calls.push(["blob", sha]);
    return { encoding: "base64", content: Buffer.from(contentByDigest.get(sha)).toString("base64") };
  };
  api.createBlob = async (content) => {
    calls.push(["createBlob", content]);
    return { sha: blobSha(content) };
  };
  api.createTree = async (input) => {
    calls.push(["createTree", input]);
    return { sha: replacementTree };
  };
  api.createCommit = async (input) => {
    calls.push(["createCommit", input]);
    assert.deepEqual(input.parents, [currentMain]);
    return { sha: replacementHead };
  };
  api.createRef = async (ref, sha) => {
    calls.push(["createRef", ref, sha]);
    return { ref, object: { sha } };
  };
  api.createPullRequest = async (input) => {
    calls.push(["createPullRequest", input]);
    const created = {
      number: 22,
      state: "open",
      head: { sha: replacementHead, ref: replacementBranch, repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
      base: { ref: "main", sha: currentMain, repo: { id: REPOSITORY_ID, full_name: "owner/media-finder" } },
      user: { login: "media-finder-release[bot]", type: "Bot" },
    };
    pullRequestsByNumber[created.number] = created;
    return { ...created };
  };
  api.getCheckRuns = async (...args) => {
    calls.push(["checks", ...args]);
    checkProbes += 1;
    return { check_runs: restCheckRuns(prRun(checkProbes === 1 ? previousHead : replacementHead)) };
  };
  api.getWorkflowRunJobs = async (...args) => {
    calls.push(["jobs", ...args]);
    return { total_count: 7, jobs: restJobs(prRun(replacementHead)) };
  };
  api.getBranchProtection = async (...args) => {
    calls.push(["protection", ...args]);
    return protectionFixture();
  };
  api.listReviewThreads = async (...args) => {
    calls.push(["threads", ...args]);
    return [];
  };
  api.listReviewRequests = async (...args) => {
    calls.push(["requests", ...args]);
    return { users: [], teams: [] };
  };
  api.listReviews = async (...args) => {
    calls.push(["reviews", ...args]);
    return [];
  };
  api.mergePullRequest = async (...args) => {
    calls.push(["merge", ...args]);
    throw new ReleaseAutomationError("fixture_stop", "Stop at the protected merge for the replacement candidate.");
  };
  api.getCommitPullRequests = async () => [];
  api.compareCommits = async (...args) => {
    calls.push(["compare", ...args]);
    return {
      total_commits: 1,
      commits: [{ sha: previousHead, html_url: `https://github.com/owner/media-finder/commit/${previousHead}` }],
    };
  };

  const preparer = {
    async createCheckout({ baseSha: requestedBase }) {
      calls.push(["checkout", requestedBase]);
      const checkoutRoot = await fsp.mkdtemp(path.join(os.tmpdir(), "release-replacement-checkout-"));
      return {
        root: checkoutRoot,
        async cleanup() {
          await fsp.rm(checkoutRoot, { recursive: true, force: true });
        },
      };
    },
    async prepare({ root: preparationRoot, baseSha: preparedBase, previousStableTag, previousStableSha, snapshot: receivedSnapshot }) {
      calls.push(["prepare", preparedBase]);
      await fsp.mkdir(path.join(preparationRoot, "docs/releases"), { recursive: true });
      await fsp.writeFile(path.join(preparationRoot, "VERSION"), candidateFiles[0].content, "utf8");
      await fsp.writeFile(path.join(preparationRoot, candidateFiles[1].path), fixture.notes, "utf8");
      return {
        schema_version: 1,
        version: "0.5.0",
        base_commit: preparedBase,
        previous_stable_tag: previousStableTag ?? "v0.4.0",
        previous_stable_sha: previousStableSha ?? SHA,
        snapshot_sha256: sha256(`${canonicalJson(receivedSnapshot)}\n`),
        base_tree_sha256: baseTreeSha256,
        candidate_tree_sha256: candidateTreeSha256,
        notes_path: candidateFiles[1].path,
        changed_files: candidateFiles.map((file) => file.path),
        expected_tree: expectedTree,
      };
    },
  };

  fixture.context = { ...fixture.context, sha: currentMain, runId: currentRunId, runAttempt: 1 };
  fixture.config = {
    ...fixture.config,
    trustedControllerSha: currentMain,
    repositoryId: REPOSITORY_ID,
  };
  fixture.input = { version: "0.5.0", currentVersion: "0.4.0" };
  fixture.preparer = preparer;
  fixture.api = api;
  fixture.attemptOne = attemptOne;
  fixture.uploads = uploads;
  fixture.currentMain = currentMain;
  fixture.previousHead = previousHead;
  fixture.previousBase = previousBase;
  fixture.replacementHead = replacementHead;
  fixture.replacementBranch = replacementBranch;
  fixture.previousBranch = previousBranch;
  return fixture;
}

test("a stale candidate is dispositioned, closed and replaced from current main", async () => {
  const fixture = await staleReplacementFixture();
  const { error } = await runReleaseAttempt("request", { ...fixture, cwd: fixture.root });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "fixture_stop");

  const names = fixture.calls.map(([name]) => name);
  const dispositionIndex = fixture.calls.findIndex(([name, value]) => name === "upload" && value === "release-op-1-stale-base-attempt-1");
  const closeIndex = fixture.calls.findIndex(([name]) => name === "updatePullRequest");
  assert.equal(dispositionIndex >= 0, true);
  assert.equal(closeIndex > dispositionIndex, true);
  assert.deepEqual(fixture.calls[closeIndex], ["updatePullRequest", 12, { state: "closed" }]);
  assert.equal(fixture.calls.filter(([name]) => name === "updatePullRequest").length, 1);
  assert.equal(fixture.calls.some(([name]) => ["deleteRef", "updateRef", "forcePush"].includes(name)), false);

  const preparation = fixture.uploads.find(({ name }) => name === "release-op-1-preparation-attempt-2");
  assert.equal(preparation !== undefined, true);
  assert.equal(preparation.payload.attempt, 2);
  assert.equal(preparation.payload.operationId, "release-op-1");
  assert.equal(preparation.payload.baseSha, fixture.currentMain);
  assert.equal(preparation.payload.notesInputSnapshot.base.commit, fixture.currentMain);

  assert.deepEqual(
    fixture.calls.filter(([name]) => name === "createRef"),
    [["createRef", `refs/heads/${fixture.replacementBranch}`, fixture.replacementHead]],
  );
  const created = fixture.calls.filter(([name]) => name === "createPullRequest");
  assert.equal(created.length, 1);
  assert.equal(created[0][1].head, fixture.replacementBranch);

  const checkCalls = fixture.calls.filter(([name]) => name === "checks");
  assert.equal(checkCalls.some(([, headSha]) => headSha === fixture.replacementHead), true);
  assert.equal(checkCalls.length > 1, true);
  assert.equal(names.indexOf("protection") < names.indexOf("merge"), true);
  assert.deepEqual(fixture.calls.find(([name]) => name === "merge").slice(1), [
    22,
    { merge_method: "squash", expected_head_sha: fixture.replacementHead },
  ]);
  assert.equal(fixture.api.listPullRequests !== undefined, true);
});

test("a stale candidate whose merge already happened is reconciled instead of replaced", async () => {
  const fixture = await staleReplacementFixture({
    pullRequestPatch: (pullRequest) => {
      pullRequest.state = "closed";
      pullRequest.merged = true;
      pullRequest.merged_at = "2026-01-02T00:00:00Z";
      pullRequest.merge_commit_sha = "1".repeat(40);
    },
  });
  const { error } = await runReleaseAttempt("request", { ...fixture, cwd: fixture.root });
  assert.equal(fixture.uploads.some(({ name }) => name.includes("preparation-attempt-2")), false);
  assert.equal(fixture.calls.some(([name]) => ["createRef", "createPullRequest", "merge"].includes(name)), false);
});

test("a manually edited stale candidate is never closed or replaced", async () => {
  const fixture = await staleReplacementFixture({
    pullRequestPatch: (pullRequest) => {
      pullRequest.head.sha = "9".repeat(40);
    },
  });
  const { error } = await runReleaseAttempt("request", { ...fixture, cwd: fixture.root });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "candidate_identity_mismatch");
  assert.equal(fixture.calls.some(([name]) => name === "updatePullRequest"), false);
  assert.equal(fixture.calls.some(([name]) => name === "createRef" || name === "createPullRequest"), false);
  assert.equal(fixture.uploads.some(({ name }) => name.includes("preparation-attempt-2")), false);
});

// ---------------------------------------------------------------------------
// Immutable checkpoint chain: producing-run provenance, a merged-SHA kind,
// explicit artifact readback, and crash reconciliation against live state.
// ---------------------------------------------------------------------------

const CHECKPOINT_FUTURE = () => new Date(Date.now() + 3600000).toISOString();

function checkpointArtifacts(uploads, { producerRunId = 205, producerControllerSha = "c".repeat(40), record } = {}) {
  return {
    async upload({ name, content }) {
      const payload = JSON.parse(content);
      uploads.push({ name, payload });
      return {
        id: 950,
        name,
        digest: `sha256:${DIGEST}`,
        expires_at: CHECKPOINT_FUTURE(),
        expired: false,
        workflow_run: {
          id: producerRunId,
          run_attempt: 1,
          repository_id: REPOSITORY_ID,
          head_repository_id: REPOSITORY_ID,
          head_sha: producerControllerSha,
        },
        ...(record === undefined ? {} : { record }),
      };
    },
  };
}

test("a checkpoint record carries the workflow run that actually produced it", async () => {
  const { persistImmutableCheckpoint, assertCheckpointRecord } = await import("./release-automation.mjs");
  const producerRunId = 205;
  const producerControllerSha = "c".repeat(40);
  for (const kind of ["pr-created", "stale-base"]) {
    const uploads = [];
    const state = executableEvidence();
    assert.equal(state.originRunId, 77, kind);
    const persisted = await persistImmutableCheckpoint(checkpointArtifacts(uploads, { producerRunId, producerControllerSha }), {
      checkpointKind: kind,
      repository: "owner/media-finder",
      operationId: "release-op-1",
      attempt: 1,
      preparationArtifactId: 901,
      preparationArtifactDigest: DIGEST,
      trustedControllerSha: state.trustedControllerSha,
      prNumber: 12,
      prHeadSha: state.preparedCommitSha,
      prBaseSha: state.baseSha,
      ...(kind === "stale-base" ? { disposition: "terminal_stale_base", currentMainSha: producerControllerSha } : {}),
      producerRunId,
      producerRunAttempt: 1,
      producerControllerSha,
    }, state);
    assert.equal(persisted.artifact.workflowRunId, producerRunId, kind);
    assert.equal(persisted.checkpoint.producerRunId, producerRunId, kind);
    assert.equal(persisted.checkpoint.producerControllerSha, producerControllerSha, kind);
    assert.equal(persisted.checkpoint.originRunId, undefined, kind);
    assert.equal(persisted.checkpoint.checkpointKind, kind, kind);
    assert.doesNotThrow(() => assertCheckpointRecord(persisted.checkpoint, {
      repository: "owner/media-finder",
      operationId: "release-op-1",
      attempt: 1,
      preparationArtifactId: 901,
      preparationArtifactDigest: DIGEST,
      producerRunId,
      producerRunAttempt: 1,
      now: Date.now(),
    }), kind);
  }
});

test("the merged-SHA checkpoint kind is persisted, validated and chained to the preparation artifact", async () => {
  const { persistImmutableCheckpoint, assertCheckpointRecord } = await import("./release-automation.mjs");
  const uploads = [];
  const state = executableEvidence();
  const base = {
    repository: "owner/media-finder",
    operationId: "release-op-1",
    attempt: 1,
    preparationArtifactId: 901,
    preparationArtifactDigest: DIGEST,
    trustedControllerSha: state.trustedControllerSha,
    prNumber: 12,
    prHeadSha: state.preparedCommitSha,
    prBaseSha: state.baseSha,
    producerRunId: 205,
    producerRunAttempt: 1,
    producerControllerSha: "c".repeat(40),
  };
  const persisted = await persistImmutableCheckpoint(checkpointArtifacts(uploads), {
    ...base,
    checkpointKind: "merged",
    mergedSha: "1".repeat(40),
  }, state);
  assert.equal(persisted.checkpoint.checkpointKind, "merged");
  assert.equal(persisted.checkpoint.mergedSha, "1".repeat(40));
  assert.equal(persisted.checkpoint.preparationArtifactId, 901);
  assert.equal(persisted.checkpoint.preparationArtifactDigest, DIGEST);
  assert.doesNotThrow(() => assertCheckpointRecord(persisted.checkpoint, {
    repository: "owner/media-finder",
    operationId: "release-op-1",
    attempt: 1,
    preparationArtifactId: 901,
    preparationArtifactDigest: DIGEST,
    producerRunId: 205,
    now: Date.now(),
  }));

  await assert.rejects(
    () => persistImmutableCheckpoint(checkpointArtifacts(uploads), { ...base, checkpointKind: "labelled" }, state),
    (error) => error instanceof ReleaseAutomationError && error.code === "checkpoint_kind_invalid",
  );
  await assert.rejects(
    () => persistImmutableCheckpoint(checkpointArtifacts(uploads), { ...base, checkpointKind: "merged" }, state),
    (error) => error instanceof ReleaseAutomationError && error.code === "checkpoint_invalid",
  );
  await assert.rejects(
    () => persistImmutableCheckpoint(checkpointArtifacts(uploads), { ...base, checkpointKind: "pr-created", prNumber: undefined }, state),
    (error) => error instanceof ReleaseAutomationError && error.code === "checkpoint_invalid",
  );
});

test("checkpoint records reject tampered, incomplete, mismatched and expired content", async () => {
  const { assertCheckpointRecord } = await import("./release-automation.mjs");
  const valid = checkpointPayload({ kind: "merged" });
  const expected = {
    repository: "owner/media-finder",
    operationId: "release-op-1",
    attempt: 1,
    preparationArtifactId: 901,
    preparationArtifactDigest: DIGEST,
    producerRunId: 205,
    producerRunAttempt: 1,
    now: Date.now(),
  };
  assert.doesNotThrow(() => assertCheckpointRecord(valid, expected));
  assert.doesNotThrow(() => assertCheckpointRecord({ ...valid }, { ...expected, operationId: undefined, attempt: undefined }));

  const reject = (value, code, label, overrides = {}) => {
    assert.throws(
      () => assertCheckpointRecord(value, { ...expected, ...overrides }),
      (error) => error instanceof ReleaseAutomationError && error.code === code,
      label,
    );
  };
  reject({ ...valid, createdAt: "2026-02-02T00:00:00.000Z" }, "checkpoint_invalid", "tampered content digest");
  reject(redigestCheckpoint({ ...valid, checkpointKind: "labelled" }), "checkpoint_kind_invalid", "unknown kind");
  reject(redigestCheckpoint((() => { const value = { ...valid }; delete value.preparationArtifactId; return value; })()), "checkpoint_invalid", "missing chain link");
  reject(redigestCheckpoint((() => { const value = { ...valid }; delete value.preparationArtifactDigest; return value; })()), "checkpoint_invalid", "missing chain digest");
  reject(redigestCheckpoint((() => { const value = { ...valid }; delete value.producerRunId; return value; })()), "checkpoint_invalid", "missing producer run");
  reject(redigestCheckpoint((() => { const value = { ...valid }; delete value.producerControllerSha; return value; })()), "checkpoint_invalid", "missing producer controller revision");
  reject(redigestCheckpoint((() => { const value = { ...valid }; delete value.mergedSha; return value; })()), "checkpoint_invalid", "missing merged SHA");
  reject(redigestCheckpoint({ ...valid, mergedSha: "not-a-sha" }), "checkpoint_invalid", "malformed merged SHA");
  reject(redigestCheckpoint({ ...valid, repository: "evil/repo" }), "repository_mismatch", "foreign repository");
  reject(redigestCheckpoint({ ...valid, operationId: "release-other" }), "checkpoint_invalid", "wrong operation");
  reject(redigestCheckpoint({ ...valid, attempt: 2 }), "checkpoint_invalid", "wrong attempt");
  reject(redigestCheckpoint({ ...valid, preparationArtifactId: 902 }), "checkpoint_invalid", "wrong preparation artifact");
  reject(redigestCheckpoint({ ...valid, preparationArtifactDigest: "a".repeat(64) }), "checkpoint_invalid", "wrong preparation digest");
  reject(redigestCheckpoint({ ...valid, producerRunId: 206 }), "checkpoint_invalid", "wrong producer run");
  reject(checkpointPayload({ kind: "merged", expiresAt: new Date(Date.now() - 1000).toISOString() }), "artifact_expired", "expired record");
});

test("artifact readback requires an explicit producing run instead of a store default", async () => {
  const calls = [];
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), "release-artifact-explicit-run-"));
  const artifact = evidence();
  const client = {
    async uploadArtifact() {
      return { id: 901, digest: DIGEST };
    },
    async getArtifact() {
      return { artifact: { id: 901, name: "release-op-1-preparation-attempt-1", digest: DIGEST } };
    },
    async downloadArtifact(...args) {
      calls.push({ method: "downloadArtifact", args });
      const [, options] = args;
      await fsp.writeFile(path.join(options.path, "release-evidence.json"), `${JSON.stringify(artifact)}\n`);
      return { downloadPath: options.path, digestMismatch: false };
    },
  };
  try {
    const store = await createActionsArtifactStore({
      client,
      repository: "owner/media-finder",
      workflowRunId: 77,
      token: "fixture-token",
      temporaryDirectory: root,
    });
    await assert.rejects(
      () => store.read(901, { digest: DIGEST }),
      (error) => error instanceof ReleaseAutomationError && error.code === "artifact_provenance_mismatch",
    );
    const recovered = await store.read(901, { digest: DIGEST, workflowRunId: 205 });
    assert.equal(recovered.contentDigest, artifact.contentDigest);
    assert.deepEqual(calls.at(-1).args[1].findBy, {
      token: "fixture-token",
      workflowRunId: 205,
      repositoryOwner: "owner",
      repositoryName: "media-finder",
    });
  } finally {
    await fsp.rm(root, { recursive: true, force: true });
  }
});

test("a recorded PR association recovers a candidate whose live listing cannot find it", async () => {
  const fixture = await staleReplacementFixture({
    checkpoints: [{ kind: "pr-created", fields: { prNumber: 12 } }],
    pullRequestPatch: (pullRequest) => {
      pullRequest.state = "closed";
      pullRequest.merged = true;
      pullRequest.merged_at = "2026-01-02T00:00:00Z";
      pullRequest.merge_commit_sha = "1".repeat(40);
    },
  });
  fixture.api.listPullRequests = async (input) => {
    fixture.calls.push(["pulls", input]);
    return [];
  };
  const { error } = await runReleaseAttempt("request", { ...fixture, cwd: fixture.root });
  assert.equal(error.code, "merged_not_on_main");
  assert.equal(fixture.uploads.some(({ name }) => name.includes("merged-attempt-1")), true);
  assert.equal(fixture.calls.some(([name, number]) => name === "pr" && Number(number) === 12), true);
  assert.equal(fixture.calls.some(([name]) => ["createRef", "createPullRequest", "merge", "updatePullRequest"].includes(name)), false);
  assert.equal(fixture.uploads.some(({ name }) => name.includes("preparation-attempt-2")), false);
});

test("a recorded terminal disposition is never written twice", async () => {
  const fixture = await staleReplacementFixture({
    checkpoints: [
      {
        kind: "stale-base",
        fields: { prNumber: 12, currentMainSha: "c".repeat(40), prHeadSha: "1".repeat(40) },
      },
    ],
  });
  const { error } = await runReleaseAttempt("request", { ...fixture, cwd: fixture.root });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "fixture_stop");
  assert.equal(fixture.uploads.some(({ name }) => name.includes("stale-base-attempt-1")), false);
  assert.deepEqual(fixture.calls.find(([name]) => name === "updatePullRequest"), ["updatePullRequest", 12, { state: "closed" }]);
  assert.equal(fixture.uploads.some(({ name }) => name.includes("preparation-attempt-2")), true);
});

test("a checkpoint that contradicts live state stops instead of guessing", async () => {
  const fixture = await staleReplacementFixture({
    checkpoints: [{ kind: "merged", fields: { prNumber: 12, mergedSha: "1".repeat(40) } }],
  });
  const { error } = await runReleaseAttempt("request", { ...fixture, cwd: fixture.root });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "mutation_ambiguous");
  assert.equal(fixture.calls.some(([name]) => ["createRef", "createPullRequest", "merge", "updatePullRequest"].includes(name)), false);
});

test("duplicate checkpoints of one kind and attempt are ambiguous", async () => {
  const fixture = await staleReplacementFixture({
    checkpoints: [
      { id: 960, kind: "merged", fields: { prNumber: 12, mergedSha: "1".repeat(40) } },
      { id: 961, kind: "merged", fields: { prNumber: 12, mergedSha: "1".repeat(40) } },
    ],
  });
  const { error } = await runReleaseAttempt("request", { ...fixture, cwd: fixture.root });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "checkpoint_ambiguous");
  assert.equal(fixture.calls.some(([name]) => ["createRef", "createPullRequest", "merge", "updatePullRequest"].includes(name)), false);
});

test("checkpoint discovery never trusts a forged producer run", async () => {
  const { discoverCheckpointChain } = await import("./release-automation.mjs");
  const fixture = await staleReplacementFixture({
    checkpoints: [
      {
        kind: "pr-created",
        fields: { prNumber: 99, prHeadSha: "9".repeat(40) },
        producerRunId: 206,
        producerControllerSha: "f".repeat(40),
        untrustedProducer: {
          id: 206,
          run_attempt: 1,
          status: "completed",
          conclusion: "success",
          event: "workflow_dispatch",
          path: "owner/media-finder/.github/workflows/prepare-release.yaml@main",
          head_sha: "f".repeat(40),
          head_branch: "main",
          actor: { login: "stranger", type: "User" },
          repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
          head_repository: { id: REPOSITORY_ID, full_name: "owner/media-finder" },
          repository_id: REPOSITORY_ID,
          head_repository_id: REPOSITORY_ID,
        },
      },
    ],
  });
  const { error } = await runReleaseAttempt("request", { ...fixture, cwd: fixture.root });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "unauthorized_actor");
  assert.equal(fixture.calls.some(([name, number]) => name === "pr" && Number(number) === 99), false);
  assert.equal(fixture.uploads.some(({ name }) => name.includes("preparation-attempt-2")), false);

  await assert.rejects(
    () => discoverCheckpointChain({
      api: fixture.api,
      auth: fixture.auth,
      artifacts: fixture.artifacts,
      context: fixture.context,
      version: "0.5.0",
      repository: "owner/media-finder",
      repositoryId: REPOSITORY_ID,
      allowedActors: ["maintainer"],
    }),
    (error) => error instanceof ReleaseAutomationError && error.code === "unauthorized_actor",
  );
});

// ---------------------------------------------------------------------------
// Exact-main/edge gating, draft creation and read-back, stable publication
// through the App, and pre-existing tag/release conflicts (OpenSpec 3.1/3.2).
// ---------------------------------------------------------------------------

test("merged-commit ancestry cannot be skipped when the compare endpoint is unavailable", async () => {
  const state = executableEvidence({ pullRequest: true });
  const calls = [];
  const fixture = executionFixture({ state, calls, protection: protectionFixture() });
  const advancedMain = "9".repeat(40);
  let mainReads = 0;
  fixture.api.getRef = async (ref) => {
    calls.push(["ref", ref]);
    if (ref !== "heads/main") return { object: { sha: state.preparedCommitSha } };
    mainReads += 1;
    return { object: { sha: mainReads === 1 ? state.baseSha : advancedMain } };
  };
  fixture.api.mergePullRequest = async (...args) => {
    calls.push(["merge", ...args]);
    return { merged: true, sha: state.preparedCommitSha, merge_commit_sha: state.preparedCommitSha };
  };
  fixture.api.getCommit = async (sha) => {
    calls.push(["commit", sha]);
    return { tree: { sha: "f".repeat(40) }, parents: [{ sha: state.baseSha }] };
  };
  const { error } = await runReleaseAttempt("execute", {
    ...fixture,
    input: { state },
    config: { allowedActors: ["maintainer"], trustedControllerSha: SHA, operationDeadlineMs: 60_000 },
    clock: steppingClock(1000),
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "merged_not_on_main");
  assert.equal(calls.some(([name]) => name === "merge"), true);
});

test("a completed main run without its edge job fails the main and edge gate", async () => {
  const mergedSha = SHA;
  const run = restWorkflowRun({ id: 710, event: "push", runAttempt: 3, path: "owner/media-finder/.github/workflows/ci.yaml@main" });
  const missingEdge = await checkMainPublication({
    async getWorkflowRuns() {
      return { total_count: 1, workflow_runs: [run] };
    },
    async getWorkflowRunJobs() {
      return { total_count: 7, jobs: restJobs(run) };
    },
  }, { ensureToken: async () => {} }, mergedSha, { repository: "owner/media-finder", repositoryId: REPOSITORY_ID });
  assert.equal(missingEdge.state, "failed");
  assert.equal(missingEdge.failures.some(({ context, reason }) => context === "publish-edge" && reason === "missing"), true);
  assert.equal(missingEdge.statuses["publish-edge"], "missing");

  const failedJobs = restJobs(run, {}, { includeEdge: true }).map((job) => job.name === "publish-edge" ? { ...job, conclusion: "failure" } : job);
  const failedEdge = await checkMainPublication({
    async getWorkflowRuns() {
      return { total_count: 1, workflow_runs: [run] };
    },
    async getWorkflowRunJobs() {
      return { total_count: 8, jobs: failedJobs };
    },
  }, { ensureToken: async () => {} }, mergedSha, { repository: "owner/media-finder", repositoryId: REPOSITORY_ID });
  assert.equal(failedEdge.state, "failed");
  assert.equal(failedEdge.failures.some(({ context }) => context === "publish-edge"), true);
});

test("a later unrelated main commit cannot satisfy the release gates", async () => {
  const mergedSha = SHA;
  const laterSha = "b".repeat(40);
  const mergedRun = restWorkflowRun({ id: 710, event: "push", runAttempt: 1, headSha: mergedSha, path: "owner/media-finder/.github/workflows/ci.yaml@main" });
  const laterRun = restWorkflowRun({ id: 711, event: "push", runAttempt: 1, headSha: laterSha, path: "owner/media-finder/.github/workflows/ci.yaml@main" });
  const makeApi = (runs) => ({
    async getWorkflowRuns() {
      return { total_count: runs.length, workflow_runs: runs };
    },
    async getWorkflowRunJobs(runId, attempt) {
      const run = runs.find((candidate) => candidate.id === Number(runId)) ?? runs[0];
      return { total_count: 8, jobs: restJobs({ ...run, run_attempt: attempt }, {}, { includeEdge: true }) };
    },
  });
  const onlyLater = await checkMainPublication(makeApi([laterRun]), { ensureToken: async () => {} }, mergedSha, {
    repository: "owner/media-finder",
    repositoryId: REPOSITORY_ID,
  });
  assert.equal(onlyLater.state, "pending");

  const both = await checkMainPublication(makeApi([laterRun, mergedRun]), { ensureToken: async () => {} }, mergedSha, {
    repository: "owner/media-finder",
    repositoryId: REPOSITORY_ID,
  });
  assert.equal(both.state, "passed");
  assert.equal(Number(both.verification.id), mergedRun.id);
});

function publicationReconciliationFixture({
  tagTargetSha,
  releases = [],
  draftTargetSha,
  draftNotes,
  edgeMissing = false,
} = {}) {
  const fixture = mergeIntentFixture();
  const { calls, state } = fixture;
  const mergedSha = "9".repeat(40);
  const notes = state.candidateFiles.find((file) => file.path === state.notesPath).content;
  const releaseRun = restWorkflowRun({
    id: 808,
    event: "release",
    path: "owner/media-finder/.github/workflows/release.yaml@main",
    headSha: mergedSha,
    runAttempt: 1,
  });
  const publicationArtifact = {
    id: 909,
    name: `stable-publication-evidence-${releaseRun.id}-${releaseRun.run_attempt}`,
    digest: `sha256:${"3".repeat(64)}`,
    expires_at: new Date(Date.now() + 3600000).toISOString(),
    expired: false,
    workflow_run: {
      id: releaseRun.id,
      run_attempt: 1,
      repository_id: REPOSITORY_ID,
      head_repository_id: REPOSITORY_ID,
      head_sha: mergedSha,
    },
  };
  const publication = canonicalPublication({
    revision: mergedSha,
    runId: releaseRun.id,
    releaseURL: "https://github.com/owner/media-finder/releases/tag/v0.5.0",
  });
  const pushRun = () => restWorkflowRun({ id: 710, event: "push", runAttempt: 1, headSha: mergedSha, path: "owner/media-finder/.github/workflows/ci.yaml@main" });
  const releaseState = { published: false, current: undefined };
  fixture.api.mergePullRequest = async (...args) => {
    calls.push(["merge", ...args]);
    return { merged: true, sha: mergedSha, merge_commit_sha: mergedSha };
  };
  fixture.api.getCommit = async (sha) => {
    calls.push(["commit", sha]);
    if (sha === mergedSha || sha === state.preparedCommitSha) {
      return { tree: { sha: state.preparedTreeSha }, parents: [{ sha: state.baseSha }] };
    }
    return { tree: { sha: state.preparedTreeSha }, parents: [{ sha: state.baseSha }] };
  };
  fixture.api.getRef = async (ref) => {
    calls.push(["ref", ref]);
    if (ref === "heads/main") return { object: { sha: releaseState.merged ? mergedSha : state.baseSha } };
    return { object: { sha: state.preparedCommitSha } };
  };
  fixture.api.getWorkflowRuns = async (input) => {
    calls.push(["runs", input]);
    if (input.event === "pull_request") {
      const run = restWorkflowRun({ id: 700, runAttempt: 1, headSha: state.preparedCommitSha, baseSha: state.baseSha });
      return { total_count: 1, workflow_runs: [run] };
    }
    if (input.event === "push") {
      const run = pushRun();
      return { total_count: 1, workflow_runs: [run] };
    }
    if (input.event === "release") return { total_count: 1, workflow_runs: [releaseRun] };
    return { workflow_runs: [] };
  };
  fixture.api.getWorkflowRunJobs = async (runId, attempt) => {
    calls.push(["jobs", runId, attempt]);
    if (Number(runId) === 700) {
      const run = restWorkflowRun({ id: 700, runAttempt: attempt, headSha: state.preparedCommitSha, baseSha: state.baseSha });
      return { total_count: 7, jobs: restJobs(run) };
    }
    const jobs = restJobs(pushRun(), {}, { includeEdge: !edgeMissing });
    return { total_count: jobs.length, jobs };
  };
  fixture.api.listRunArtifacts = async (runId) => {
    calls.push(["run-artifacts", runId]);
    if (Number(runId) === releaseRun.id) return { total_count: 1, artifacts: [publicationArtifact] };
    return { total_count: 0, artifacts: [] };
  };
  fixture.api.getArtifact = async (artifactId) => {
    calls.push(["artifact", artifactId]);
    if (Number(artifactId) === publicationArtifact.id) return publicationArtifact;
    return metadataForPreparation();
  };
  const metadataForPreparation = () => ({
    id: 901,
    name: "release-op-1-preparation-attempt-1",
    digest: `sha256:${DIGEST}`,
    expires_at: new Date(Date.now() + 3600000).toISOString(),
    expired: false,
    workflow_run: {
      id: 77,
      run_attempt: 1,
      repository_id: REPOSITORY_ID,
      head_repository_id: REPOSITORY_ID,
      head_sha: SHA,
    },
  });
  fixture.api.listReleases = async (...args) => {
    calls.push(["releases", ...args]);
    return releaseState.current === undefined ? releases : [releaseState.current, ...releases.filter((release) => release.id !== releaseState.current.id)];
  };
  fixture.api.createRelease = async (input) => {
    calls.push(["createRelease", input]);
    releaseState.current = {
      id: 55,
      tag_name: input.tag_name,
      target_commitish: draftTargetSha ?? input.target_commitish,
      body: draftNotes ?? input.body,
      draft: input.draft,
      prerelease: input.prerelease,
      html_url: `https://github.com/owner/media-finder/releases/tag/${input.tag_name}`,
    };
    return { ...releaseState.current };
  };
  fixture.api.getRelease = async (id) => {
    calls.push(["release", id]);
    if (releaseState.current !== undefined && Number(id) === releaseState.current.id) return { ...releaseState.current };
    return releases.find((release) => Number(release.id) === Number(id));
  };
  fixture.api.updateRelease = async (id, input) => {
    calls.push(["updateRelease", id, input]);
    releaseState.current = { ...releaseState.current, ...input };
    return { ...releaseState.current };
  };
  fixture.api.getTagRef = async (tag) => {
    calls.push(["tag", tag]);
    if (tagTargetSha !== undefined) return { object: { type: "commit", sha: tagTargetSha } };
    if (!releaseState.published) throw new ReleaseAutomationError("github_api_error", "Not found.", { status: 404 });
    return { object: { type: "commit", sha: mergedSha } };
  };
  const originalMerge = fixture.api.mergePullRequest;
  fixture.api.mergePullRequest = async (...args) => {
    releaseState.merged = true;
    return originalMerge(...args);
  };
  const originalUpdate = fixture.api.updateRelease;
  fixture.api.updateRelease = async (id, input) => {
    const result = await originalUpdate(id, input);
    if (input.draft === false) releaseState.published = true;
    return result;
  };
  const baseRead = fixture.artifacts.read;
  fixture.artifacts = {
    async read(id, options) {
      if (Number(id) === publicationArtifact.id) return publication;
      return baseRead(id, options);
    },
  };
  fixture.config = {
    ...fixture.config,
    // Keep the run's evidence output outside the repository worktree.
    evidencePath: path.join(os.tmpdir(), `release-publication-evidence-${process.pid}-${Date.now()}.json`),
  };
  fixture.mergedSha = mergedSha;
  fixture.releaseRun = releaseRun;
  fixture.publication = publication;
  fixture.notes = notes;
  return fixture;
}

test("the draft release is created, read back and published through the App", async () => {
  const fixture = publicationReconciliationFixture();
  const { result, error } = await runReleaseAttempt("execute", {
    ...fixture,
    input: { state: fixture.state },
    config: { ...fixture.config, operationDeadlineMs: 60_000 },
  });
  assert.equal(error, undefined);
  assert.equal(result.state.status, "complete");
  assert.deepEqual(result.publication.actualTags.map(({ name }) => name), ["v0.5.0", "0.5", "latest"]);

  const created = fixture.calls.find(([name]) => name === "createRelease");
  assert.equal(created !== undefined, true);
  assert.equal(created[1].draft, true);
  assert.equal(created[1].prerelease, false);
  assert.equal(created[1].tag_name, "v0.5.0");
  assert.equal(created[1].target_commitish, fixture.mergedSha);
  assert.equal(created[1].body, fixture.notes);
  const published = fixture.calls.find(([name]) => name === "updateRelease");
  assert.deepEqual(published, ["updateRelease", 55, { draft: false }]);
  assert.equal(fixture.calls.some(([name]) => name === "merge"), true);
});

test("a pre-existing stable tag at another commit stops publication", async () => {
  const fixture = publicationReconciliationFixture({ tagTargetSha: "b".repeat(40) });
  const { error } = await runReleaseAttempt("execute", {
    ...fixture,
    input: { state: fixture.state },
    config: { ...fixture.config, operationDeadlineMs: 60_000 },
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "tag_conflict");
  assert.equal(fixture.calls.some(([name]) => name === "createRelease"), false);
});

test("two releases claiming the stable tag are ambiguous and never replaced", async () => {
  const release = (id, extra = {}) => ({
    id,
    tag_name: "v0.5.0",
    target_commitish: "9".repeat(40),
    body: undefined,
    draft: false,
    prerelease: false,
    html_url: `https://github.com/owner/media-finder/releases/${id}`,
    ...extra,
  });
  const fixture = publicationReconciliationFixture({ releases: [release(55), release(56)] });
  fixture.api.listReleases = async () => [
    release(55, { body: fixture.notes }),
    release(56, { body: fixture.notes }),
  ];
  const { error } = await runReleaseAttempt("execute", {
    ...fixture,
    input: { state: fixture.state },
    config: { ...fixture.config, operationDeadlineMs: 60_000 },
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "release_ambiguous");
  assert.equal(fixture.calls.some(([name]) => ["createRelease", "updateRelease"].includes(name)), false);
});

test("a pre-existing release whose target or notes differ is a conflict", async () => {
  for (const variant of ["target", "notes"]) {
    const fixture = publicationReconciliationFixture();
    const mergedSha = fixture.mergedSha;
    const existing = {
      id: 55,
      tag_name: "v0.5.0",
      target_commitish: variant === "target" ? "b".repeat(40) : mergedSha,
      body: variant === "notes" ? "Different notes" : fixture.notes,
      draft: false,
      prerelease: false,
      html_url: "https://github.com/owner/media-finder/releases/tag/v0.5.0",
    };
    fixture.api.listReleases = async () => [existing];
    const { error } = await runReleaseAttempt("execute", {
      ...fixture,
      input: { state: fixture.state },
      config: { ...fixture.config, operationDeadlineMs: 60_000 },
    });
    assert.equal(error instanceof ReleaseAutomationError, true, variant);
    assert.equal(error.code, "release_conflict", variant);
    assert.equal(fixture.calls.some(([name]) => name === "updateRelease"), false, variant);
  }
});

test("a draft read-back whose target or notes differ is never published", async () => {
  for (const options of [
    { draftTargetSha: "b".repeat(40) },
    { draftNotes: "Different notes" },
  ]) {
    const fixture = publicationReconciliationFixture(options);
    const { error } = await runReleaseAttempt("execute", {
      ...fixture,
      input: { state: fixture.state },
      config: { ...fixture.config, operationDeadlineMs: 60_000 },
    });
    assert.equal(error instanceof ReleaseAutomationError, true);
    assert.equal(error.code, "release_readback_mismatch");
    assert.equal(fixture.calls.some(([name]) => name === "updateRelease"), false);
  }
});

// ---------------------------------------------------------------------------
// Canonical structured evidence and the English workflow summary (OpenSpec 3.5).
// ---------------------------------------------------------------------------

function completedReleaseState() {
  const mergedSha = "9".repeat(40);
  return {
    ...executableEvidence({ pullRequest: true }),
    status: "complete",
    mergedSha,
    releaseId: 55,
    releaseUrl: "https://github.com/owner/media-finder/releases/tag/v0.5.0",
    mainWorkflowRunId: 710,
    edgeWorkflowRunId: 710,
    edgeJobId: 719,
    releaseWorkflowRunId: 808,
    publication: canonicalPublication({ revision: mergedSha, runId: 808 }),
  };
}

test("structured evidence is built from the canonical actualTags projection", () => {
  const state = completedReleaseState();
  assert.equal(Object.hasOwn(state.publication, "tags"), false);
  const evidence = buildStructuredEvidence(state);
  assert.deepEqual(evidence.tagNames, ["v0.5.0", "0.5", "latest"]);
  assert.deepEqual(evidence.tagDetails.map(({ name }) => name), ["v0.5.0", "0.5", "latest"]);
  assert.equal(evidence.digest, `sha256:${DIGEST}`);
  assert.deepEqual(evidence.platforms, ["linux/amd64", "linux/arm64"]);
  assert.equal(evidence.sourceRevision, state.mergedSha);
  assert.equal(evidence.status, "complete");
  assert.equal(evidence.nextAction, "No action required.");
  assert.equal(evidence.repository, "owner/media-finder");
  assert.equal(evidence.attempt, 1);
  assert.equal(evidence.pullRequest.url, "https://github.com/owner/media-finder/pull/12");
  assert.equal(evidence.pullRequest.headSha, state.preparedCommitSha);
  assert.equal(evidence.pullRequest.baseSha, state.baseSha);
  assert.equal(evidence.workflow.mainRunId, 710);
  assert.equal(evidence.workflow.edgeRunId, 710);
  assert.equal(evidence.workflow.edgeJobId, 719);
  assert.equal(evidence.workflow.releaseRunId, 808);
  assert.equal(evidence.workflow.mainRunURL, "https://github.com/owner/media-finder/actions/runs/710");
  assert.equal(evidence.workflow.releaseRunURL, "https://github.com/owner/media-finder/actions/runs/808");
  assert.equal(JSON.stringify(evidence).includes('"publication"'), false);
});

test("the summary formatter is idempotent and reports every required identity", () => {
  const state = completedReleaseState();
  const projected = buildStructuredEvidence(state);
  assert.deepEqual(buildStructuredEvidence(projected), projected);

  const summary = formatWorkflowSummary(projected);
  assert.equal(summary.includes("## Stable release complete"), true);
  assert.equal(summary.includes("https://github.com/owner/media-finder/pull/12"), true);
  assert.equal(summary.includes("https://github.com/owner/media-finder/releases/tag/v0.5.0"), true);
  assert.equal(summary.includes("Main/edge workflow runs: 710 / 710"), true);
  assert.equal(summary.includes("Release workflow run: 808"), true);
  assert.equal(summary.includes("v0.5.0, 0.5, latest"), true);
  assert.equal(summary.includes(`sha256:${DIGEST}`), true);
  assert.equal(summary.includes("linux/amd64, linux/arm64"), true);
  assert.equal(summary.includes(state.mergedSha), true);
  assert.equal(summary.includes("not verified"), false);
  assert.equal(summary.includes("not created"), false);
  assert.equal(summary.includes("unknown"), false);
  assert.equal(summary.includes(canonicalJson(projected)), true);
  assert.equal(formatWorkflowSummary(state).includes(canonicalJson(projected)), true);
});

test("the summary never reports success while publication evidence is missing", () => {
  const incomplete = buildStructuredEvidence({
    ...executableEvidence({ pullRequest: true }),
    status: "complete",
    mergedSha: "9".repeat(40),
  });
  assert.equal(incomplete.status, "incomplete");
  assert.notEqual(incomplete.nextAction, "No action required.");
  const summary = formatWorkflowSummary(incomplete);
  assert.equal(summary.startsWith("## Stable release complete"), false);
  assert.equal(summary.includes("## Stable release incomplete"), true);
});

test("the failure path keeps its own next action, error block and boundary", async () => {
  const { buildBlockedEvidence } = await import("./release-automation.mjs");
  const blocked = buildBlockedEvidence({
    error: new ReleaseAutomationError("operation_deadline_exceeded", "The operation-wide release deadline elapsed.", {
      completedBoundary: {
        operationId: "release-op-1",
        repository: "owner/media-finder",
        attempt: 2,
        status: "pr_created",
        prNumber: 12,
        preparedCommitSha: "e".repeat(40),
        baseSha: SHA,
      },
    }),
  });
  const summary = formatWorkflowSummary(blocked);
  assert.equal(summary.includes(blocked.nextAction), true);
  assert.equal(summary.includes("Resume the same operation after reviewing the recorded completed boundary."), false);
  assert.equal(summary.includes("operation_deadline_exceeded"), true);
  assert.equal(summary.includes("https://github.com/owner/media-finder/pull/12"), true);
  assert.equal(summary.includes("attempt 2"), true);
  assert.equal(summary.includes(canonicalJson(blocked)), true);

  // Any evidence object that already carries its own next action and error
  // keeps both through the summary projection.
  const legacy = {
    schemaVersion: 1,
    status: "blocked",
    operationId: "release-op-1",
    nextAction: "Review the safe diagnostic and resume only after the recorded blocker is resolved.",
    error: { code: "tag_conflict", message: "Stable tag already exists.", details: {} },
  };
  const legacySummary = formatWorkflowSummary(legacy);
  assert.equal(legacySummary.includes("Review the safe diagnostic"), true);
  assert.equal(legacySummary.includes("tag_conflict"), true);
});

test("a completed release reports every required identity in its structured evidence", async () => {
  const fixture = publicationReconciliationFixture();
  const { result, error } = await runReleaseAttempt("execute", {
    ...fixture,
    input: { state: fixture.state },
    config: { ...fixture.config, operationDeadlineMs: 60_000 },
  });
  assert.equal(error, undefined);
  const evidence = result.evidence;
  assert.equal(evidence.status, "complete");
  assert.equal(evidence.repository, "owner/media-finder");
  assert.equal(evidence.attempt, 1);
  assert.equal(evidence.pullRequest.url, "https://github.com/owner/media-finder/pull/12");
  assert.equal(evidence.pullRequest.headSha, fixture.state.preparedCommitSha);
  assert.equal(evidence.pullRequest.baseSha, fixture.state.baseSha);
  assert.equal(evidence.mergedSha, fixture.mergedSha);
  assert.equal(evidence.release.url, "https://github.com/owner/media-finder/releases/tag/v0.5.0");
  assert.equal(evidence.workflow.mainRunId, 710);
  assert.equal(evidence.workflow.edgeRunId, 710);
  assert.equal(evidence.workflow.releaseRunId, 808);
  assert.deepEqual(evidence.tagNames, ["v0.5.0", "0.5", "latest"]);
  assert.equal(evidence.digest, `sha256:${DIGEST}`);
  assert.deepEqual(evidence.platforms, ["linux/amd64", "linux/arm64"]);
  assert.equal(evidence.sourceRevision, fixture.mergedSha);
  assert.equal(evidence.nextAction, "No action required.");
  assert.equal(evidence.schemaVersion, 1);
});

// ---------------------------------------------------------------------------
// Repair round 2 (independent review of 3.5): authoritative next actions,
// bounded pagination of listing reads, drift-flag subtraction and canonical
// summary field names.
// ---------------------------------------------------------------------------

function pageAwareClient({ label, key, overrides = {} } = {}) {
  const endpoints = [];
  const pageOf = (endpoint) => Number(new URL(`https://example.invalid${endpoint}`).searchParams.get("page") ?? 1);
  return {
    endpoints,
    api: new GitHubRestApi({
      repository: "owner/media-finder",
      auth: {
        async request(method, endpoint) {
          endpoints.push(endpoint);
          const page = pageOf(endpoint);
          const handler = overrides[label] ?? overrides.default;
          return handler(page, endpoint);
        },
      },
    }),
    key,
  };
}

function firstPageFullThenShort(first = 100, total = 101) {
  return (page) => {
    const items = page === 1
      ? Array.from({ length: first }, (_, index) => ({ id: 1000 + index }))
      : Array.from({ length: total - first }, (_, index) => ({ id: 5000 + index }));
    return { total_count: total, workflow_runs: items, check_runs: items, jobs: items, artifacts: items, releases: items };
  };
}

test("listing reads paginate with the bounded loop instead of failing on history length", async () => {
  const pages = [];
  const api = new GitHubRestApi({
    repository: "owner/media-finder",
    auth: {
      async request(method, endpoint) {
        pages.push(endpoint);
        const page = Number(new URL(`https://example.invalid${endpoint}`).searchParams.get("page") ?? 1);
        const items = page === 1
          ? Array.from({ length: 100 }, (_, index) => ({ id: 1000 + index }))
          : [{ id: 5000 }];
        return {
          total_count: 101,
          workflow_runs: items,
          check_runs: items,
          jobs: items,
          artifacts: items,
          releases: items,
        };
      },
    },
  });

  const runs = await api.getWorkflowRuns({ headSha: SHA, event: "push", branch: "main" });
  assert.equal(runs.workflow_runs.length, 101);
  const checks = await api.getCheckRuns(SHA);
  assert.equal(checks.check_runs.length, 101);
  const jobs = await api.getWorkflowRunJobs(700, 1);
  assert.equal(jobs.jobs.length, 101);
  const artifacts = await api.listRunArtifacts(700);
  assert.equal(artifacts.artifacts.length, 101);
  const releases = await api.listReleases();
  assert.equal(releases.releases.length, 101);
  assert.equal(pages.some((endpoint) => endpoint.includes("page=2")), true);
  assert.equal(pages.filter((endpoint) => endpoint.includes("page=2")).length >= 5, true);

  const overflowing = new GitHubRestApi({
    repository: "owner/media-finder",
    auth: {
      async request(method, endpoint) {
        return {
          workflow_runs: Array.from({ length: 100 }, (_, index) => ({ id: index })),
        };
      },
    },
  });
  await assert.rejects(
    () => overflowing.getWorkflowRuns({ headSha: SHA }),
    (error) => error instanceof ReleaseAutomationError && error.code === "pagination_incomplete",
  );
});

function baseChangedFixture() {
  const state = executableEvidence({ pullRequest: true });
  const calls = [];
  const fixture = executionFixture({ state, calls, protection: protectionFixture() });
  const advancedMain = "9".repeat(40);
  fixture.api.getRef = async (...args) => {
    calls.push(["ref", ...args]);
    if (args[0] !== "heads/main") return { object: { sha: state.preparedCommitSha } };
    // Main advanced after the checks: the candidate is stale.
    return { object: { sha: advancedMain } };
  };
  fixture.api.updatePullRequest = async (...args) => {
    calls.push(["updatePullRequest", ...args]);
    return { state: "closed" };
  };
  fixture.artifacts = {
    async read() {
      return state;
    },
    async upload({ name, content }) {
      calls.push(["upload", name]);
      return {
        id: 950,
        name,
        digest: `sha256:${DIGEST}`,
        expires_at: new Date(Date.now() + 3600000).toISOString(),
        expired: false,
        workflow_run: { id: 77, run_attempt: 1, repository_id: REPOSITORY_ID, head_repository_id: REPOSITORY_ID, head_sha: SHA },
      };
    },
  };
  return { fixture, state, calls };
}

test("a real base_changed failure carries its next action into the summary", async () => {
  const { buildBlockedEvidence } = await import("./release-automation.mjs");
  const { fixture, state } = baseChangedFixture();
  const { error } = await runReleaseAttempt("execute", {
    ...fixture,
    input: { state },
    config: { allowedActors: ["maintainer"], trustedControllerSha: SHA },
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "base_changed");
  assert.equal(typeof error.details.resume, "string");

  const blocked = buildBlockedEvidence({ error });
  assert.equal(blocked.nextAction, error.details.resume);
  const summary = formatWorkflowSummary(blocked);
  assert.equal(summary.includes(error.details.resume), true);
  assert.equal(summary.includes("next bounded candidate attempt"), true);
  assert.equal(summary.includes("Review the safe diagnostic"), false);
  assert.equal(summary.includes("base_changed"), true);
});

test("a caller-supplied next action cannot override the authoritative projection", () => {
  const state = completedReleaseState();
  const overridden = buildStructuredEvidence({ ...state, nextAction: "Caller supplied text" });
  assert.equal(overridden.nextAction, "No action required.");
  const failed = buildStructuredEvidence({
    ...executableEvidence({ pullRequest: true }),
    status: "blocked",
    nextAction: "Caller supplied text",
    error: { code: "base_changed", message: "Stale base.", details: { resume: "Re-dispatch the same canonical version for the next attempt." } },
  });
  assert.equal(failed.nextAction, "Re-dispatch the same canonical version for the next attempt.");
});

test("the summary kind uses one canonical name for the tag identities", () => {
  const state = completedReleaseState();
  const evidence = buildStructuredEvidence(state);
  assert.deepEqual(evidence.tagNames, ["v0.5.0", "0.5", "latest"]);
  assert.equal(evidence.tags, undefined);
  assert.deepEqual(evidence.tagDetails.map(({ name }) => name), ["v0.5.0", "0.5", "latest"]);
  const summary = formatWorkflowSummary(evidence);
  assert.equal(summary.includes("v0.5.0, 0.5, latest"), true);
});

test("a workflow SHA that is not current main is refused even with a drift flag", async () => {
  const fixture = await preparationFixture({ omitSnapshot: true });
  const { error } = await runReleaseAttempt("prepare", {
    ...fixture,
    context: { ...fixture.context, sha: "b".repeat(40) },
    config: { ...fixture.config, trustedControllerSha: "b".repeat(40), allowDispatchShaDrift: true },
    cwd: fixture.root,
  });
  assert.equal(error instanceof ReleaseAutomationError, true);
  assert.equal(error.code, "base_identity_mismatch");
  assert.equal(fixture.calls.some(([name]) => name === "upload"), false);
});
