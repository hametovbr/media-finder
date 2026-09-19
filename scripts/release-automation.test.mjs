import assert from "node:assert/strict";
import crypto from "node:crypto";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  GitHubAppAuthenticator,
  GitHubRestApi,
  ReleaseAutomationError,
  GITHUB_ACTIONS_APP_ID,
  REQUIRED_CHECK_CONTEXTS,
  assertReleaseMetadata,
  assertApprovedBranchProtection,
  assertPreparationArtifact,
  buildPreparationEvidence,
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
    value.prHeadSha = SHA;
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

function executionFixture({ state, calls, protection, protectionError, pullRequestUserType, pullRequestRef, repositoryOwnerType = "User", mergeError } = {}) {
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
      return {
        state: "open",
        head: {
          sha: SHA,
          repo: { full_name: "owner/media-finder" },
          ...(pullRequestRef === undefined ? {} : { ref: pullRequestRef }),
        },
        base: { ref: "main", repo: { full_name: "owner/media-finder" } },
        ...(pullRequestUserType === undefined ? {} : { user: { type: pullRequestUserType } }),
      };
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
      const run = restWorkflowRun({ id: 700, runAttempt: 1 });
      return {
        check_runs: restCheckRuns(run),
      };
    },
    async getWorkflowRuns(input) {
      calls.push(["runs", input]);
      if (input.event === "pull_request") {
        const run = restWorkflowRun({ id: 700, runAttempt: 1 });
        return {
          total_count: 1,
          workflow_runs: [run],
        };
      }
      return { workflow_runs: [] };
    },
    async getWorkflowRunJobs(...args) {
      calls.push(["jobs", ...args]);
      const run = restWorkflowRun({ id: 700, runAttempt: args[1] });
      return { total_count: 7, jobs: restJobs(run) };
    },
    async getBranchProtection(...args) {
      calls.push(["protection", ...args]);
      if (protectionError) throw protectionError;
      return protection;
    },
    async getRef(...args) {
      calls.push(["ref", ...args]);
      return { object: { sha: SHA } };
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
          installationId: 456,
          repository: "owner/media-finder",
          repositoryId: REPOSITORY_ID,
        },
      },
      async ensureToken() {},
    },
    artifacts: { async read() { return state; } },
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
    if (String(url).endsWith("/app")) return response(200, { id: 123, client_id: "Iv1.fixture" });
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
  assert.deepEqual(calls.map(([name]) => name), ["actor", "origin-run", "actor", "artifact", "pulls", "repository", "protection"]);
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
    "repository",
    "protection",
  ]);
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
  assert.deepEqual(calls.map(([name]) => name), ["actor", "origin-run", "actor", "artifact", "pulls", "commit", "commit", "tree", "blob", "pr"]);
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

    const recovered = await store.read(901, { digest });
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
      () => store.read(902, { digest: DIGEST }),
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

async function preparationFixture({ uploadFailure = false, metadataFailure, readbackFailure } = {}) {
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
  const preparer = {
    async prepare({ root: preparationRoot, version, snapshot: preparationSnapshot }) {
      assert.equal(preparationRoot, root);
      assert.equal(version, "0.5.0");
      assert.deepEqual(preparationSnapshot, snapshot);
      await fsp.mkdir(path.join(root, "docs/releases"), { recursive: true });
      await fsp.writeFile(path.join(root, "VERSION"), candidateFiles[0].content, "utf8");
      await fsp.writeFile(path.join(root, candidateFiles[1].path), notes, "utf8");
      return {
        schema_version: 1,
        version: "0.5.0",
        base_commit: SHA,
        previous_stable_tag: "v0.4.0",
        previous_stable_sha: SHA,
        snapshot_sha256: sha256(`${canonicalJson(snapshot)}\n`),
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
    input: {
      version: "0.5.0",
      currentVersion: "0.4.0",
      notesInputSnapshot: snapshot,
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
      return [];
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
      return { number: 12, head: { sha: preparedCommitSha } };
    },
    async getPullRequest(...args) {
      calls.push(["pr", ...args]);
      return {
        state: pullRequestMerged ? "closed" : "open",
        ...(pullRequestMerged ? { merged: true, merged_at: "2026-01-02T00:00:00Z", merge_commit_sha: SHA } : {}),
        head: { sha: preparedCommitSha, ref: branch, repo: { full_name: "owner/media-finder" } },
        base: { ref: "main", repo: { full_name: "owner/media-finder" } },
      };
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
  try {
    const result = await runReleaseAutomation({
      phase: "execute",
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
