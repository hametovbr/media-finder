/**
 * Trusted stable-release controller.
 *
 * This file deliberately keeps the release policy in small, injectable pieces.
 * The default CLI talks to GitHub with a repository-scoped GitHub App token;
 * tests and local verification use the same controller with fixture adapters.
 * Candidate code is only run by the credential-free preparer boundary.
 */

import crypto from "node:crypto";
import fs from "node:fs";
import fsp from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";
import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

export const RELEASE_AUTOMATION_SCHEMA_VERSION = 1;
export const PREPARATION_ARTIFACT_RETENTION_DAYS = 90;
export const TOKEN_RENEWAL_WINDOW_SECONDS = 5 * 60;
export const MAX_CANDIDATE_ATTEMPTS = 3;
// Hosted release verification can legitimately wait through the pull-request
// checks, main verification, and the stable publication workflow. Keep the
// controller deadline below the workflow's 330-minute job limit while still
// renewing the installation token as each API operation starts.
export const DEFAULT_OPERATION_DEADLINE_MS = 5 * 60 * 60 * 1000;
// A single budget for the whole operation may never reach the hosted job limit;
// an operator-provided deadline above this bound is refused instead of relying
// on the runner to kill the job without a resumable boundary.
const MAX_OPERATION_DEADLINE_MS = DEFAULT_OPERATION_DEADLINE_MS;
// Every immutable checkpoint is one approved kind. The chain is: the
// preparation artifact, the PR association it produced, a terminal stale-attempt
// disposition when the base moved, and the merged SHA that completed the
// operation.
const RELEASE_CHECKPOINT_KINDS = Object.freeze(["pr-created", "stale-base", "merged"]);
// The credential-free preparer process has its own bound; the operation budget
// can only tighten it, never extend it.
const DEFAULT_PREPARER_TIMEOUT_MS = 120_000;
export const MAX_POLL_DELAY_MS = 30 * 1000;
export const CI_WORKFLOW_PATH = ".github/workflows/ci.yaml";
export const RELEASE_WORKFLOW_PATH = ".github/workflows/release.yaml";
export const PREPARATION_WORKFLOW_PATH = ".github/workflows/prepare-release.yaml";

// These are the seven required contexts produced by verify.yaml. The API may
// report them as either a check-run name or a workflow job name; both forms
// are normalized before comparison.
export const REQUIRED_CHECK_CONTEXTS = Object.freeze([
  "verification / documentation",
  "verification / python",
  "verification / unit",
  "verification / integration",
  "verification / contract",
  "verification / browser",
  "verification / image",
]);

// GitHub's built-in Actions application owns checks emitted by workflow jobs.
// Branch protection returns this App ID in each required-status-check entry;
// requiring it prevents an unrelated integration from satisfying a required
// context with the same display name.
export const GITHUB_ACTIONS_APP_ID = 15368;

// Installation tokens are intentionally requested with this exact repository
// permission set. Keep the value immutable so callers cannot accidentally add
// a write-capable administration grant or rely on a broader installation token.
export const RELEASE_APP_PERMISSIONS = Object.freeze({
  actions: "read",
  administration: "read",
  checks: "read",
  contents: "write",
  metadata: "read",
  pull_requests: "write",
});

const SHA_PATTERN = /^[0-9a-f]{40}$/i;
const DIGEST_PATTERN = /^[0-9a-f]{64}$/i;
const IMAGE_DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/i;
const VERSION_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const REPOSITORY_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const OPERATION_PATTERN = /^release-[a-z0-9-]{1,80}$/;
const ARTIFACT_NAME_PATTERN = /^[A-Za-z0-9_.-]{1,200}$/;
const SAFE_PATH_PATTERN = /^(?!\/)(?!.*(?:^|\/)\.\.(?:\/|$))(?!\.git(?:\/|$))[A-Za-z0-9_.@+\-/]{1,300}$/;
const SAFE_URL_PATTERN = /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:[/?#][^\s]*)?$/;
const CREDENTIAL_KEYS = new Set([
  "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
  "ACTIONS_RUNTIME_TOKEN",
  "GH_TOKEN",
  "GITHUB_TOKEN",
  "NODE_AUTH_TOKEN",
  "NPM_TOKEN",
  "RELEASE_APP_PRIVATE_KEY",
  "RELEASE_APP_TOKEN",
  "REGISTRY_PASSWORD",
  "DOCKER_PASSWORD",
]);
const CREDENTIAL_KEY_PATTERN = /(token|secret|password|private[_-]?key|credential|authorization)/i;
const MAX_EVIDENCE_BYTES = 5 * 1024 * 1024;
const MAX_CANDIDATE_FILES = 200;
const MAX_CANDIDATE_BYTES = 25 * 1024 * 1024;
const MAX_HISTORY_COMMITS = 500;
// The compare endpoint is paginated. History capture walks every provider page
// and fails closed with the reported bound instead of silently truncating the
// release history to one page.
const HISTORY_PAGE_SIZE = 100;
const MAX_HISTORY_PAGES = Math.ceil(MAX_HISTORY_COMMITS / HISTORY_PAGE_SIZE) + 1;
const MAX_RESPONSE_BYTES = 25 * 1024 * 1024;
const MAX_TRACKED_FILES = 100_000;
const MAX_WORKTREE_BYTES = 512 * 1024 * 1024;
const MAX_COLLECTION_ITEMS = 10_000;
const MAX_ANNOTATED_TAG_DEPTH = 4;

export class ReleaseAutomationError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "ReleaseAutomationError";
    this.code = code;
    this.details = sanitizeDetails(details);
  }
}

function sanitizeDetails(value, depth = 0) {
  if (depth > 4) return "[truncated]";
  if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    if (typeof value === "string" && value.length > 500) return `${value.slice(0, 497)}...`;
    return value;
  }
  if (Array.isArray(value)) return value.slice(0, 100).map((item) => sanitizeDetails(item, depth + 1));
  if (typeof value !== "object") return undefined;
  const result = {};
  for (const [key, item] of Object.entries(value).slice(0, 100)) {
    if (CREDENTIAL_KEY_PATTERN.test(key)) continue;
    result[key] = sanitizeDetails(item, depth + 1);
  }
  return result;
}

function fail(code, message, details = {}) {
  throw new ReleaseAutomationError(code, message, details);
}

function asObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail("malformed_response", `${label} must be an object.`);
  }
  return value;
}

function boundedString(value, label, maxLength = 1000) {
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) {
    fail("malformed_input", `${label} must be a bounded non-empty string.`);
  }
  return value;
}

function normalizeSha(value, label = "SHA") {
  if (typeof value !== "string" || !SHA_PATTERN.test(value)) {
    fail("identity_mismatch", `${label} must be a 40-character Git SHA.`);
  }
  return value.toLowerCase();
}

function normalizeDigest(value, label = "digest") {
  if (typeof value !== "string" || !DIGEST_PATTERN.test(value)) {
    fail("identity_mismatch", `${label} must be a SHA-256 digest.`);
  }
  return value.toLowerCase();
}

function normalizeArtifactDigest(value, label = "artifact digest") {
  if (typeof value === "string" && /^sha256:[0-9a-f]{64}$/i.test(value)) {
    return value.slice("sha256:".length).toLowerCase();
  }
  return normalizeDigest(value, label);
}

function artifactSdkDigest(value, label = "artifact digest") {
  return `sha256:${normalizeArtifactDigest(value, label)}`;
}

function normalizeRepository(value) {
  if (typeof value !== "string" || !REPOSITORY_PATTERN.test(value)) {
    fail("identity_mismatch", "Repository must be in OWNER/REPOSITORY form.");
  }
  return value;
}

function normalizeOperationId(value) {
  if (typeof value !== "string" || !OPERATION_PATTERN.test(value)) {
    fail("identity_mismatch", "Operation identity is malformed.");
  }
  return value;
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, canonicalize(item)]),
    );
  }
  return value;
}

export function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

export function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function jsonDigest(value) {
  return sha256(canonicalJson(value));
}

function ensureBoundedJson(value, label, maxBytes = MAX_EVIDENCE_BYTES) {
  const encoded = canonicalJson(value);
  if (Buffer.byteLength(encoded, "utf8") > maxBytes) {
    fail("evidence_too_large", `${label} exceeds the bounded evidence limit.`);
  }
  return encoded;
}

function scanForCredential(value, label = "evidence", seen = new Set()) {
  if (value === null || value === undefined) return;
  if (typeof value === "string") {
    if (value.length > 0 && (CREDENTIAL_KEYS.has(label) || CREDENTIAL_KEY_PATTERN.test(label))) {
      fail("credential_in_evidence", `${label} cannot be persisted in release evidence.`);
    }
    return;
  }
  if (typeof value !== "object") return;
  if (seen.has(value)) fail("malformed_input", "Evidence must not contain cyclic values.");
  seen.add(value);
  for (const [key, item] of Object.entries(value)) scanForCredential(item, key, seen);
  seen.delete(value);
}

function parseStableVersion(value, label = "version") {
  if (typeof value !== "string") fail("invalid_version", `${label} must be a canonical stable SemVer.`);
  const match = value.match(VERSION_PATTERN);
  if (!match) fail("invalid_version", `${label} must use canonical X.Y.Z stable SemVer.`);
  return {
    majorText: match[1],
    minorText: match[2],
    patchText: match[3],
    text: value,
  };
}

function compareDecimalStrings(left, right) {
  const a = String(left).replace(/^0+(?=\d)/, "");
  const b = String(right).replace(/^0+(?=\d)/, "");
  if (a.length !== b.length) return a.length < b.length ? -1 : 1;
  if (a === b) return 0;
  return a < b ? -1 : 1;
}

export function compareStableVersions(left, right) {
  const a = typeof left === "string" ? parseStableVersion(left) : left;
  const b = typeof right === "string" ? parseStableVersion(right) : right;
  return compareDecimalStrings(a.majorText, b.majorText) ||
    compareDecimalStrings(a.minorText, b.minorText) ||
    compareDecimalStrings(a.patchText, b.patchText);
}

export function validateRequestedVersion(value, { currentVersion, latestStableVersion } = {}) {
  const requested = parseStableVersion(value, "requested version");
  if (currentVersion !== undefined && currentVersion !== null) {
    const current = parseStableVersion(currentVersion, "current product version");
    if (compareStableVersions(requested, current) <= 0) {
      fail("version_not_increasing", "Requested version must be newer than the current product version.", {
        currentVersion: current.text,
        requestedVersion: requested.text,
      });
    }
  }
  if (latestStableVersion !== undefined && latestStableVersion !== null) {
    const latest = parseStableVersion(latestStableVersion, "latest stable version");
    if (compareStableVersions(requested, latest) <= 0) {
      fail("version_not_increasing", "Requested version must be newer than the latest stable release.", {
        latestStableVersion: latest.text,
        requestedVersion: requested.text,
      });
    }
  }
  return requested;
}

export function validateDispatchContext(context, {
  repository,
  allowedActors = [],
  trustedControllerSha,
} = {}) {
  const value = asObject(context, "dispatch context");
  const eventName = value.eventName ?? value.event_name;
  const ref = value.ref ?? value.refName;
  const actualRepository = value.repository ?? value.repositoryFullName ?? value.repository_full_name;
  const actor = value.actor ?? value.initiatingActor;
  const sha = value.sha ?? value.workflowSha ?? value.workflow_sha;
  if (eventName !== "workflow_dispatch") fail("untrusted_trigger", "Release preparation only accepts workflow_dispatch.");
  if (ref !== "refs/heads/main") fail("untrusted_ref", "Release preparation must execute from refs/heads/main.");
  if (repository && actualRepository?.toLowerCase() !== normalizeRepository(repository).toLowerCase()) {
    fail("repository_mismatch", "Workflow repository does not match the configured repository.");
  }
  normalizeRepository(actualRepository);
  boundedString(actor, "initiating actor", 100);
  normalizeSha(sha, "trusted workflow SHA");
  if (trustedControllerSha && normalizeSha(trustedControllerSha, "trusted controller SHA") !== sha.toLowerCase()) {
    fail("controller_revision_mismatch", "Workflow did not execute the trusted controller revision.");
  }
  if (allowedActors.length > 0) {
    const allowed = new Set(allowedActors.map((item) => String(item).trim().toLowerCase()).filter(Boolean));
    if (!allowed.has(actor.toLowerCase())) fail("unauthorized_actor", "Initiating actor is not an allowed repository writer.");
  }
  return {
    eventName,
    ref,
    repository: actualRepository,
    actor,
    sha: sha.toLowerCase(),
    runId: normalizeRunId(value.runId ?? value.run_id ?? process.env.GITHUB_RUN_ID),
    runAttempt: normalizeRunAttempt(value.runAttempt ?? value.run_attempt ?? process.env.GITHUB_RUN_ATTEMPT),
  };
}

function normalizeRunId(value) {
  const numeric = Number(value);
  if (!Number.isSafeInteger(numeric) || numeric <= 0) fail("identity_mismatch", "Workflow run ID is malformed.");
  return numeric;
}

function normalizeRunAttempt(value) {
  const numeric = Number(value ?? 1);
  if (!Number.isSafeInteger(numeric) || numeric <= 0) fail("identity_mismatch", "Workflow run attempt is malformed.");
  return numeric;
}

function normalizeRequiredRunAttempt(value, label = "workflow run attempt", code = "identity_mismatch") {
  if (value === undefined || value === null || value === "") {
    fail(code, `${label} is required and must be authenticated by the provider.`);
  }
  const numeric = Number(value);
  if (!Number.isSafeInteger(numeric) || numeric <= 0) fail(code, `${label} is malformed.`);
  return numeric;
}

function normalizePositiveInteger(value, label) {
  const numeric = Number(value);
  if (!Number.isSafeInteger(numeric) || numeric <= 0) fail("identity_mismatch", `${label} is malformed.`);
  return numeric;
}

export function sanitizeCredentialEnvironment(environment = process.env) {
  const result = { ...environment };
  for (const key of Object.keys(result)) {
    if (CREDENTIAL_KEYS.has(key) || CREDENTIAL_KEY_PATTERN.test(key)) delete result[key];
  }
  // These runner values can mint credentials even when the well-known names
  // above are absent. They are intentionally not inherited by the preparer.
  for (const key of ["ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_RUNTIME_URL", "GITHUB_SERVER_URL"]) {
    if (key.startsWith("ACTIONS_")) delete result[key];
  }
  return result;
}

function base64Url(value) {
  return Buffer.from(value).toString("base64url");
}

export function createAppJwt({ appId, privateKey, now = () => Date.now() }) {
  boundedString(String(appId ?? ""), "App ID", 200);
  boundedString(privateKey, "App private key", 20_000);
  const issuedAt = Math.floor(now() / 1000) - 30;
  const payload = {
    iat: issuedAt,
    exp: issuedAt + 9 * 60,
    iss: String(appId),
  };
  const encodedHeader = base64Url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const encodedPayload = base64Url(JSON.stringify(payload));
  const input = `${encodedHeader}.${encodedPayload}`;
  let signature;
  try {
    signature = crypto.createSign("RSA-SHA256").update(input).end().sign(privateKey, "base64url");
  } catch {
    fail("app_credentials_invalid", "App private key cannot be used for authentication.");
  }
  return `${input}.${signature}`;
}

function normalizePrivateKey(value) {
  if (typeof value !== "string" || value.trim() === "") fail("missing_credentials", "Release App credentials are not configured.");
  return value.replaceAll("\\n", "\n");
}

async function readResponseBody(response) {
  const text = await response.text();
  if (Buffer.byteLength(text, "utf8") > MAX_RESPONSE_BYTES) fail("response_too_large", "GitHub response exceeds the bounded response limit.");
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch {
    fail("malformed_response", "GitHub returned malformed JSON.");
  }
}

export class GitHubAppAuthenticator {
  constructor({
    fetchImpl = globalThis.fetch,
    apiUrl = "https://api.github.com",
    appId,
    repository,
    expectedRepositoryId,
    installationId,
    privateKey,
    now = () => Date.now(),
    renewalWindowSeconds = TOKEN_RENEWAL_WINDOW_SECONDS,
  } = {}) {
    if (typeof fetchImpl !== "function") fail("missing_http_client", "A fetch implementation is required.");
    this.fetchImpl = fetchImpl;
    this.apiUrl = apiUrl.replace(/\/$/, "");
    this.appId = appId;
    this.repository = normalizeRepository(repository);
    this.expectedRepositoryId = expectedRepositoryId === undefined || expectedRepositoryId === "" ? undefined : Number(expectedRepositoryId);
    if (this.expectedRepositoryId !== undefined && (!Number.isSafeInteger(this.expectedRepositoryId) || this.expectedRepositoryId <= 0)) {
      fail("repository_scope_mismatch", "Configured repository ID is malformed.");
    }
    this.installationId = installationId === undefined || installationId === "" ? undefined : Number(installationId);
    if (this.installationId !== undefined && (!Number.isSafeInteger(this.installationId) || this.installationId <= 0)) {
      fail("installation_mismatch", "Configured installation ID is malformed.");
    }
    this.privateKey = privateKey;
    this.now = now;
    this.renewalWindowSeconds = renewalWindowSeconds;
    this.current = undefined;
  }

  async rawRequest(method, endpoint, { token, body, scheme } = {}) {
    const headers = {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "media-finder-release-controller",
    };
    // GitHub accepts the Bearer scheme for both App JWTs and installation
    // access tokens. Keep one explicit scheme for every authenticated request
    // so a token can never be accidentally sent through a legacy `token`
    // branch with different semantics.
    if (token) headers.Authorization = `${scheme ?? "Bearer"} ${token}`;
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
    }
    let response;
    try {
      response = await this.fetchImpl(`${this.apiUrl}${endpoint}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      fail("github_unavailable", "GitHub API is unavailable.");
    }
    const parsed = await readResponseBody(response);
    return { response, value: parsed };
  }

  async issueInstallationToken() {
    const privateKey = normalizePrivateKey(this.privateKey);
    const jwt = createAppJwt({ appId: this.appId, privateKey, now: this.now });
    const appResult = await this.rawRequest("GET", "/app", { token: jwt, scheme: "Bearer" });
    if (!appResult.response.ok) fail("app_identity_unavailable", "Release App identity could not be verified.");
    const app = asObject(appResult.value, "App identity");
    const configuredApp = String(this.appId);
    const appIdentities = [app.id, app.client_id, app.node_id]
      .filter((identity) => identity !== undefined && identity !== null)
      .map((identity) => String(identity));
    if (appIdentities.length === 0 || !appIdentities.includes(configuredApp)) {
      fail("app_identity_mismatch", "GitHub returned a different App identity.");
    }
    let installationEndpoint;
    if (this.installationId !== undefined) {
      if (!Number.isSafeInteger(this.installationId) || this.installationId <= 0) fail("installation_mismatch", "Installation ID is malformed.");
      installationEndpoint = `/app/installations/${this.installationId}`;
    } else {
      installationEndpoint = `/repos/${this.repository}/installation`;
    }
    const installationResult = await this.rawRequest("GET", installationEndpoint, { token: jwt, scheme: "Bearer" });
    if (!installationResult.response.ok) fail("installation_unavailable", "Release App installation could not be verified.");
    const installation = asObject(installationResult.value, "App installation");
    // The GitHub App slug determines the `slug[bot]` login that the App uses
    // for the pull requests it creates. Capture it from the authenticated App
    // response so PR authorship can be compared against the exact login of
    // this installation instead of a weaker "some bot" heuristic.
    if (typeof app.slug !== "string" || !/^[A-Za-z0-9-]{1,200}$/.test(app.slug)) {
      fail("app_identity_mismatch", "GitHub App identity does not expose an authenticated bot login.");
    }
    const installationId = Number(installation.id ?? this.installationId);
    if (!Number.isSafeInteger(installationId) || installationId <= 0) fail("installation_mismatch", "GitHub installation identity is incomplete.");
    if (installation.app_id !== undefined && app.id !== undefined && String(installation.app_id) !== String(app.id)) {
      fail("installation_mismatch", "Installation belongs to a different App.");
    }
    const installedRepository = installation.repository ?? installation.repositories?.[0];
    if (installedRepository) {
      if (String(installedRepository.full_name ?? "").toLowerCase() !== this.repository.toLowerCase()) {
        fail("repository_scope_mismatch", "Release App installation is not scoped to this repository.");
      }
      if (this.expectedRepositoryId !== undefined && Number(installedRepository.id) !== this.expectedRepositoryId) {
        fail("repository_scope_mismatch", "Release App installation repository ID does not match.");
      }
    }
    const tokenResult = await this.rawRequest("POST", `/app/installations/${installationId}/access_tokens`, {
      token: jwt,
      scheme: "Bearer",
      body: {
        repositories: [this.repository.split("/")[1]],
        permissions: { ...RELEASE_APP_PERMISSIONS },
      },
    });
    if (!tokenResult.response.ok) fail("token_issuance_failed", "Repository-scoped installation token could not be issued.");
    const issued = asObject(tokenResult.value, "installation token");
    const token = boundedString(issued.token, "installation token", 10_000);
    const expiresAt = Date.parse(issued.expires_at);
    if (!Number.isFinite(expiresAt) || expiresAt <= this.now()) fail("token_issuance_failed", "Installation token expiry is invalid.");
    const permissions = asObject(issued.permissions, "installation token permissions");
    const requiredPermissions = RELEASE_APP_PERMISSIONS;
    const permissionKeys = Object.keys(permissions).sort();
    if (
      JSON.stringify(permissionKeys) !== JSON.stringify(Object.keys(requiredPermissions).sort()) ||
      Object.entries(requiredPermissions).some(([permission, level]) => permissions[permission] !== level)
    ) {
      fail("token_scope_mismatch", "Installation token lacks the exact required repository permissions.");
    }
    // Installation-token responses do not themselves prove which selected
    // repositories the token can access. Ask GitHub using the newly issued
    // token and require an exact one-repository set before allowing writes.
    const repositoryResult = await this.rawRequest("GET", "/installation/repositories", {
      token,
      scheme: "Bearer",
    });
    if (!repositoryResult.response.ok) fail("repository_scope_mismatch", "Installation token repository scope could not be verified.");
    const repositories = asArray(asObject(repositoryResult.value, "installation repositories").repositories, "installation repositories");
    if (repositories.length !== 1) fail("repository_scope_mismatch", "Installation token is scoped to more than the target repository.");
    const scopedRepository = asObject(repositories[0], "scoped repository");
    if (String(scopedRepository.full_name ?? "").toLowerCase() !== this.repository.toLowerCase()) {
      fail("repository_scope_mismatch", "Installation token repository scope does not match the target repository.");
    }
    if (this.expectedRepositoryId !== undefined && Number(scopedRepository.id) !== this.expectedRepositoryId) {
      fail("repository_scope_mismatch", "Installation token repository ID does not match trusted configuration.");
    }
    const scopedRepositoryId = Number(scopedRepository.id);
    if (!Number.isSafeInteger(scopedRepositoryId) || scopedRepositoryId <= 0) fail("repository_scope_mismatch", "Installation token repository ID is malformed.");
    const identity = {
      appId: app.id === undefined ? undefined : Number(app.id),
      appClientId: app.client_id ? String(app.client_id) : undefined,
      appSlug: String(app.slug),
      installationId,
      repository: this.repository,
      repositoryId: scopedRepositoryId,
    };
    if (identity.appId !== undefined && (!Number.isSafeInteger(identity.appId) || identity.appId <= 0)) {
      fail("app_identity_mismatch", "GitHub App identity ID is malformed.");
    }
    this.current = { token, expiresAt, identity };
    return { token, expiresAt, identity };
  }

  async ensureToken() {
    const now = this.now();
    if (
      this.current &&
      this.current.expiresAt - now > this.renewalWindowSeconds * 1000
    ) {
      return this.current;
    }
    return this.issueInstallationToken();
  }

  async request(method, endpoint, body) {
    const current = await this.ensureToken();
    const result = await this.rawRequest(method, endpoint, { token: current.token, body });
    if (result.response.status === 401) {
      fail("token_expired", "Installation token expired during an API mutation; reconcile state before retrying.", {
        method,
        endpoint,
        mutating: method !== "GET" && method !== "HEAD",
      });
    }
    if (!result.response.ok) {
      const message = typeof result.value?.message === "string" ? result.value.message : "GitHub API request failed.";
      fail("github_api_error", message, { status: result.response.status, method, endpoint });
    }
    return result.value;
  }
}

export class GitHubRestApi {
  constructor({ auth, repository, graphql } = {}) {
    if (!auth || typeof auth.request !== "function") fail("missing_authenticator", "GitHubRestApi requires an App authenticator.");
    this.auth = auth;
    this.repository = normalizeRepository(repository);
    this.apiRepository = `/repos/${this.repository}`;
    this.graphql = graphql;
  }

  request(method, endpoint, body) {
    return this.auth.request(method, endpoint, body);
  }

  getRepository() { return this.request("GET", this.apiRepository); }
  getInstallation() { return this.request("GET", `${this.apiRepository}/installation`); }
  getRef(ref) { return this.request("GET", `${this.apiRepository}/git/ref/${ref.replace(/^refs\//, "")}`); }
  getCommit(sha) { return this.request("GET", `${this.apiRepository}/git/commits/${normalizeSha(sha)}`); }
  getTree(sha) { return this.request("GET", `${this.apiRepository}/git/trees/${normalizeSha(sha)}?recursive=1`); }
  getBlob(sha) { return this.request("GET", `${this.apiRepository}/git/blobs/${normalizeSha(sha)}`); }
  async getTreeDigest(sha) {
    const tree = await this.getTree(sha);
    if (tree.truncated === true) fail("tree_digest_unavailable", "GitHub returned a truncated tree.");
    const allEntries = asArray(tree.tree ?? tree, "tree entries");
    for (const entry of allEntries) {
      const value = asObject(entry, "tree entry");
      if (value.type !== "blob" && value.type !== "tree") {
        fail("tree_digest_unavailable", "Tree contains an unsupported entry type.");
      }
    }
    const entries = allEntries.filter((entry) => entry.type === "blob");
    return computeTreeDigestFromEntries(this, entries);
  }
  getCommitPullRequests(sha) {
    return this.paginatedItems({
      endpoint: `${this.apiRepository}/commits/${normalizeSha(sha)}/pulls`,
      key: "pulls",
      label: "commit pull requests",
    });
  }
  createBlob(content) { return this.request("POST", `${this.apiRepository}/git/blobs`, { content, encoding: "utf-8" }); }
  createTree(input) { return this.request("POST", `${this.apiRepository}/git/trees`, input); }
  createCommit(input) { return this.request("POST", `${this.apiRepository}/git/commits`, input); }
  createRef(ref, sha) { return this.request("POST", `${this.apiRepository}/git/refs`, { ref, sha }); }
  getPullRequest(number) { return this.request("GET", `${this.apiRepository}/pulls/${Number(number)}`); }
  createPullRequest(input) { return this.request("POST", `${this.apiRepository}/pulls`, input); }
  updatePullRequest(number, input) { return this.request("PATCH", `${this.apiRepository}/pulls/${Number(number)}`, input); }
  mergePullRequest(number, input = {}) {
    const value = asObject(input, "merge request");
    if (value.merge_method !== "squash") fail("merge_policy_violation", "Release candidates may only use protected squash merge.");
    // The protected merge carries exactly the squash policy and the expected
    // head identity. Refuse any additional field so no caller can smuggle an
    // administrative, bypass or protection-related option into the request.
    const allowed = new Set(["merge_method", "expected_head_sha", "sha"]);
    for (const key of Object.keys(value)) {
      if (!allowed.has(key)) {
        fail("merge_policy_violation", "Protected squash merge accepts only the expected head identity.", { field: key });
      }
    }
    const body = { merge_method: value.merge_method };
    const expectedHeadSha = value.expected_head_sha === undefined ? undefined : normalizeSha(value.expected_head_sha, "expected merge head SHA");
    const explicitSha = value.sha === undefined ? undefined : normalizeSha(value.sha, "expected merge head SHA");
    if (expectedHeadSha !== undefined && explicitSha !== undefined && expectedHeadSha !== explicitSha) {
      fail("merge_policy_violation", "Conflicting expected head identities in the protected merge request.");
    }
    const sha = explicitSha ?? expectedHeadSha;
    if (sha === undefined) fail("merge_identity_missing", "Protected squash merge requires an expected head SHA.");
    body.sha = sha;
    return this.request("PUT", `${this.apiRepository}/pulls/${Number(number)}/merge`, body);
  }
  /**
   * One bounded pagination loop for every listing read. It walks provider pages
   * until a short page proves the collection is complete and fails closed only
   * when the collection genuinely exceeds the controller bound, so a long
   * repository history can no longer be mistaken for untrusted evidence.
   */
  async paginatedItems({ endpoint, key, label, query = {} }) {
    const all = [];
    for (let page = 1; page <= MAX_COLLECTION_ITEMS / 100; page += 1) {
      const search = new URLSearchParams({ per_page: "100", ...query });
      if (page > 1) search.set("page", String(page));
      const value = await this.request("GET", `${endpoint}?${search}`);
      const items = asArray(Array.isArray(value) ? value : value[key] ?? value, label);
      all.push(...items);
      if (all.length > MAX_COLLECTION_ITEMS) fail("pagination_incomplete", `${label} exceed the bounded collection limit.`);
      if (items.length < 100) return all;
    }
    fail("pagination_incomplete", `GitHub returned more ${label} than the bounded controller can inspect.`);
  }
  listPullRequests(input = {}) {
    return this.paginatedItems({
      endpoint: `${this.apiRepository}/pulls`,
      key: "pulls",
      label: "pull requests",
      query: { state: input.state ?? "open", base: input.base ?? "main" },
    });
  }
  listReviews(number) {
    return this.paginatedItems({
      endpoint: `${this.apiRepository}/pulls/${Number(number)}/reviews`,
      key: "reviews",
      label: "reviews",
    });
  }
  listReviewRequests(number) { return this.request("GET", `${this.apiRepository}/pulls/${Number(number)}/requested_reviewers`); }
  async listReviewThreads(number) {
    const [owner, repo] = this.repository.split("/");
    const nodes = [];
    let cursor = null;
    for (let page = 0; page < 100; page += 1) {
      const query = `query($owner:String!,$repo:String!,$number:Int!,$after:String){repository(owner:$owner,name:$repo){pullRequest(number:$number){reviewThreads(first:100,after:$after){nodes{isResolved} pageInfo{hasNextPage endCursor}}}}}`;
      const variables = { owner, repo, number: Number(number), after: cursor };
      const result = this.graphql
        ? await this.graphql(query, variables)
        : await this.request("POST", "/graphql", { query, variables });
      if (result?.errors?.length) fail("review_threads_unavailable", "GitHub review-thread evidence is unavailable.");
      const connection = result?.data?.repository?.pullRequest?.reviewThreads ?? result?.repository?.pullRequest?.reviewThreads;
      if (!connection || !Array.isArray(connection.nodes) || !connection.pageInfo || typeof connection.pageInfo.hasNextPage !== "boolean") {
        fail("review_threads_unavailable", "GitHub review-thread evidence is malformed.");
      }
      nodes.push(...connection.nodes);
      if (!connection.pageInfo.hasNextPage) return nodes;
      if (typeof connection.pageInfo.endCursor !== "string" || connection.pageInfo.endCursor.length === 0) {
        fail("review_threads_unavailable", "GitHub review-thread pagination is incomplete.");
      }
      cursor = connection.pageInfo.endCursor;
    }
    fail("review_threads_unavailable", "GitHub returned more review threads than the bounded controller can inspect.");
  }
  async getCheckRuns(sha) {
    const items = await this.paginatedItems({
      endpoint: `${this.apiRepository}/commits/${normalizeSha(sha)}/check-runs`,
      key: "check_runs",
      label: "check runs",
    });
    return { total_count: items.length, check_runs: items };
  }
  async getWorkflowRuns(input = {}) {
    const query = {};
    if (input.headSha) query.head_sha = normalizeSha(input.headSha);
    if (input.event) query.event = input.event;
    if (input.branch) query.branch = input.branch;
    // The REST route takes a workflow file name (for example `ci.yaml`),
    // while the run provenance returned by GitHub carries the full path. Keep
    // those identities separate: callers still validate the full path below.
    const workflowId = input.workflow ? String(input.workflow).split("/").at(-1) : undefined;
    const endpoint = workflowId
      ? `${this.apiRepository}/actions/workflows/${encodeURIComponent(workflowId)}/runs`
      : `${this.apiRepository}/actions/runs`;
    const items = await this.paginatedItems({ endpoint, key: "workflow_runs", label: "workflow runs", query });
    return { total_count: items.length, workflow_runs: items };
  }
  getWorkflowRun(id) { return this.request("GET", `${this.apiRepository}/actions/runs/${Number(id)}`); }
  getWorkflowRunAttempt(id, runAttempt) {
    const numericId = normalizePositiveInteger(id, "workflow run ID");
    const numericAttempt = normalizeRequiredRunAttempt(runAttempt, "workflow run attempt");
    return this.request("GET", `${this.apiRepository}/actions/runs/${numericId}/attempts/${numericAttempt}`);
  }
  async getWorkflowRunJobs(id, runAttempt = 1) {
    const numericId = normalizePositiveInteger(id, "workflow run ID");
    const numericAttempt = normalizeRunAttempt(runAttempt);
    const items = await this.paginatedItems({
      endpoint: `${this.apiRepository}/actions/runs/${numericId}/attempts/${numericAttempt}/jobs`,
      key: "jobs",
      label: "workflow run jobs",
    });
    return { total_count: items.length, jobs: items };
  }
  getTagRef(tag) { return this.request("GET", `${this.apiRepository}/git/ref/tags/${encodeURIComponent(tag)}`); }
  getTag(sha) { return this.request("GET", `${this.apiRepository}/git/tags/${normalizeSha(sha)}`); }
  async listReleases() {
    const items = await this.paginatedItems({ endpoint: `${this.apiRepository}/releases`, key: "releases", label: "releases" });
    return { total_count: items.length, releases: items };
  }
  getReleaseByTag(tag) { return this.request("GET", `${this.apiRepository}/releases/tags/${encodeURIComponent(tag)}`); }
  createRelease(input) { return this.request("POST", `${this.apiRepository}/releases`, input); }
  getRelease(id) { return this.request("GET", `${this.apiRepository}/releases/${Number(id)}`); }
  updateRelease(id, input) { return this.request("PATCH", `${this.apiRepository}/releases/${Number(id)}`, input); }
  compareCommits(base, head, options = {}) {
    const query = new URLSearchParams();
    if (options.page !== undefined) query.set("page", String(normalizePositiveInteger(options.page, "compare page")));
    if (options.perPage !== undefined) query.set("per_page", String(normalizePositiveInteger(options.perPage, "compare page size")));
    const suffix = query.size > 0 ? `?${query}` : "";
    return this.request("GET", `${this.apiRepository}/compare/${encodeURIComponent(base)}...${normalizeSha(head)}${suffix}`);
  }
  getArtifact(id) { return this.request("GET", `${this.apiRepository}/actions/artifacts/${Number(id)}`); }
  async listRunArtifacts(runId) {
    const numericId = normalizePositiveInteger(runId, "workflow run ID");
    const items = await this.paginatedItems({
      endpoint: `${this.apiRepository}/actions/runs/${numericId}/artifacts`,
      key: "artifacts",
      label: "workflow run artifacts",
    });
    return { total_count: items.length, artifacts: items };
  }
  async listArtifacts(input = {}) {
    const items = await this.paginatedItems({
      endpoint: `${this.apiRepository}/actions/artifacts`,
      key: "artifacts",
      label: "artifacts",
      query: input.name === undefined ? {} : { name: input.name },
    });
    return { total_count: items.length, artifacts: items };
  }
  listBranches() {
    return this.paginatedItems({
      endpoint: `${this.apiRepository}/branches`,
      key: "branches",
      label: "repository branches",
    });
  }
  getCollaboratorPermission(actor) {
    return this.request("GET", `${this.apiRepository}/collaborators/${encodeURIComponent(actor)}/permission`);
  }
  getBranchProtection(branch = "main") {
    return this.request("GET", `${this.apiRepository}/branches/${encodeURIComponent(branch)}/protection`);
  }
}

function ensureSafeEvidenceValue(value, label) {
  scanForCredential(value, label);
  ensureBoundedJson(value, label);
  return value;
}

function normalizeCandidateFiles(files) {
  if (!Array.isArray(files) || files.length === 0 || files.length > MAX_CANDIDATE_FILES) {
    fail("candidate_malformed", "Candidate files must be a bounded non-empty array.");
  }
  const seen = new Set();
  let totalBytes = 0;
  const normalized = files.map((entry) => {
    const item = asObject(entry, "candidate file");
    const filePath = boundedString(item.path, "candidate file path", 300);
    if (!SAFE_PATH_PATTERN.test(filePath)) fail("candidate_path_invalid", "Candidate contains an unsafe file path.", { path: filePath });
    if (seen.has(filePath)) fail("candidate_malformed", "Candidate contains a duplicate file path.", { path: filePath });
    seen.add(filePath);
    const mode = item.mode === undefined ? "100644" : String(item.mode);
    if (!/^(100644|100755|120000)$/.test(mode)) fail("candidate_malformed", "Candidate file mode is unsupported.", { path: filePath });
    let content;
    if (typeof item.content === "string") {
      content = item.content;
    } else if (typeof item.contentBase64 === "string") {
      try {
        content = Buffer.from(item.contentBase64, "base64").toString("utf8");
      } catch {
        fail("candidate_malformed", "Candidate file content is not valid base64.", { path: filePath });
      }
    } else {
      fail("candidate_malformed", "Candidate file content is missing.", { path: filePath });
    }
    totalBytes += Buffer.byteLength(content, "utf8");
    if (totalBytes > MAX_CANDIDATE_BYTES) fail("candidate_too_large", "Candidate content exceeds the bounded size limit.");
    return { path: filePath, mode, content };
  });
  return normalized.sort((left, right) => compareSafePaths(left.path, right.path));
}

function normalizeExpectedTreeMap(value) {
  const tree = asObject(value, "expected tree");
  const entries = Object.entries(tree);
  if (entries.length === 0 || entries.length > 100_000) fail("candidate_malformed", "Expected tree must be a bounded non-empty object.");
  const normalized = {};
  for (const [filePath, entry] of entries) {
    if (!SAFE_PATH_PATTERN.test(filePath)) fail("candidate_path_invalid", "Expected tree contains an unsafe path.", { path: filePath });
    const item = asObject(entry, "expected tree entry");
    const mode = String(item.mode ?? "");
    if (!/^(100644|100755|120000)$/.test(mode)) fail("candidate_malformed", "Expected tree contains an unsupported file mode.", { path: filePath });
    normalized[filePath] = { mode, sha256: normalizeDigest(item.sha256, "expected file digest") };
  }
  return Object.fromEntries(Object.entries(normalized).sort(([left], [right]) => compareSafePaths(left, right)));
}

function candidateFilesFromPreparationResult(result, cwd) {
  const value = asObject(result, "preparer output");
  if (value.schema_version !== 1) fail("preparer_output_invalid", "Preparer output schema is unsupported.");
  const expectedTree = normalizeExpectedTreeMap(value.expected_tree);
  const changedFiles = value.changed_files;
  if (!Array.isArray(changedFiles) || changedFiles.length === 0 || changedFiles.length > MAX_CANDIDATE_FILES) fail("preparer_output_invalid", "Preparer changed_files is malformed.");
  const files = [];
  const seen = new Set();
  let totalBytes = 0;
  for (const filePathValue of changedFiles) {
    const filePath = boundedString(filePathValue, "changed file path", 300);
    if (!Object.hasOwn(expectedTree, filePath) || seen.has(filePath) || !SAFE_PATH_PATTERN.test(filePath)) fail("preparer_output_invalid", "Preparer changed_files does not match expected_tree.", { path: filePath });
    seen.add(filePath);
    const absolute = path.resolve(cwd, filePath);
    if (!absolute.startsWith(`${path.resolve(cwd)}${path.sep}`) || !fs.existsSync(absolute) || fs.lstatSync(absolute).isSymbolicLink() || !fs.lstatSync(absolute).isFile()) fail("preparer_output_invalid", "Preparer output file is not a regular workspace file.", { path: filePath });
    const content = fs.readFileSync(absolute);
    const expected = expectedTree[filePath];
    if (sha256(content) !== expected.sha256) fail("preparer_output_invalid", "Preparer output content does not match expected_tree.", { path: filePath });
    totalBytes += content.length;
    if (totalBytes > MAX_CANDIDATE_BYTES) fail("candidate_too_large", "Prepared changed files exceed the bounded size limit.");
    files.push({ path: filePath, mode: expected.mode, content: content.toString("utf8") });
  }
  const candidateTreeSha256 = normalizeDigest(value.candidate_tree_sha256, "candidate tree digest");
  return {
    version: parseStableVersion(value.version, "preparer version").text,
    baseCommit: normalizeSha(value.base_commit, "preparer base commit"),
    previousStableTag: boundedString(value.previous_stable_tag, "preparer previous stable tag", 100),
    previousStableSha: normalizeSha(value.previous_stable_sha, "preparer previous stable SHA"),
    snapshotSha256: normalizeDigest(value.snapshot_sha256, "preparer snapshot digest"),
    baseTreeSha256: normalizeDigest(value.base_tree_sha256, "preparer base tree digest"),
    candidateTreeSha256,
    notesPath: boundedString(value.notes_path, "preparer notes path", 300),
    expectedTree,
    changedFiles: files.sort((left, right) => compareSafePaths(left.path, right.path)),
    raw: value,
  };
}

export function computeCandidateTreeDigest(files) {
  const normalized = normalizeCandidateFiles(files);
  return jsonDigest(normalized.map(({ path: filePath, mode, content }) => ({
    path: filePath,
    mode,
    sha: sha256(content),
  })));
}

function normalizeExpectedTree(expectedTree, files) {
  if (typeof expectedTree === "string") return normalizeDigest(expectedTree, "expected tree digest");
  const tree = asObject(expectedTree ?? {}, "expected tree");
  const digest = tree.digest ?? tree.sha256 ?? computeCandidateTreeDigest(files);
  return normalizeDigest(digest, "expected tree digest");
}

export function buildPreparationEvidence(input) {
  const value = asObject(input, "preparation evidence");
  const repository = normalizeRepository(value.repository);
  const version = parseStableVersion(value.version, "requested version");
  const operationId = normalizeOperationId(value.operationId);
  const attempt = Number(value.attempt);
  if (!Number.isSafeInteger(attempt) || attempt < 1 || attempt > MAX_CANDIDATE_ATTEMPTS) fail("attempt_invalid", "Candidate attempt is outside the allowed bound.");
  const files = normalizeCandidateFiles(value.candidateFiles ?? value.files ?? (Array.isArray(value.expectedTree?.files) ? value.expectedTree.files : undefined));
  const expectedTree = value.expectedTreeMap
    ? normalizeExpectedTreeMap(value.expectedTreeMap)
    : value.expectedTree && !Array.isArray(value.expectedTree) && value.expectedTree.files === undefined
      ? normalizeExpectedTreeMap(value.expectedTree)
      : undefined;
  const expectedTreeDigest = normalizeDigest(value.candidateTreeSha256 ?? value.expectedTree?.digest ?? (expectedTree ? value.expectedTreeDigest : undefined) ?? computeCandidateTreeDigest(files), "expected tree digest");
  const notesInputSnapshot = ensureSafeEvidenceValue(value.notesInputSnapshot ?? {}, "notesInputSnapshot");
  const evidence = {
    schemaVersion: RELEASE_AUTOMATION_SCHEMA_VERSION,
    evidenceKind: "release-preparation",
    repository,
    repositoryId: normalizePositiveInteger(value.repositoryId, "repository ID"),
    appId: normalizePositiveInteger(value.appId, "App ID"),
    installationId: normalizePositiveInteger(value.installationId, "installation ID"),
    operationId,
    attempt,
    trustedControllerSha: normalizeSha(value.trustedControllerSha, "trusted controller SHA"),
    originRunId: normalizeRunId(value.originRunId),
    originRunAttempt: normalizeRequiredRunAttempt(value.originRunAttempt, "origin workflow run attempt", "artifact_provenance_mismatch"),
    baseSha: normalizeSha(value.baseSha, "base SHA"),
    previousStableTag: boundedString(value.previousStableTag, "previous stable tag", 100),
    previousStableSha: normalizeSha(value.previousStableSha, "previous stable SHA"),
    version: version.text,
    notesInputSnapshot,
    notesInputDigest: jsonDigest(notesInputSnapshot),
    expectedTree: expectedTree
      ? { digest: expectedTreeDigest, files: expectedTree }
      : {
        digest: expectedTreeDigest,
        files: files.map(({ path: filePath, mode, content }) => ({ path: filePath, mode, sha256: sha256(content), content })),
      },
    candidateFiles: files,
    notesPath: value.notesPath,
    changedFiles: value.changedFiles ?? files.map(({ path: filePath }) => filePath),
    candidateTreeSha256: value.candidateTreeSha256 ?? expectedTreeDigest,
    // Preparation is durable only after the exact Git objects have been
    // created and checked. These identities are therefore required in the
    // unshipped artifact schema rather than being optional execution fields.
    preparedCommitSha: normalizeSha(value.preparedCommitSha, "prepared commit SHA"),
    preparedTreeSha: normalizeSha(value.preparedTreeSha, "prepared tree SHA"),
    createdAt: value.createdAt ?? new Date().toISOString(),
  };
  ensureSafeEvidenceValue(evidence, "preparation evidence");
  const contentDigest = jsonDigest(evidence);
  return { ...evidence, contentDigest };
}

export function assertPreparationArtifact(value, expected = {}) {
  const evidence = asObject(value, "preparation artifact");
  if (evidence.schemaVersion !== RELEASE_AUTOMATION_SCHEMA_VERSION || evidence.evidenceKind !== "release-preparation") {
    fail("artifact_schema_invalid", "Preparation artifact schema is unsupported.");
  }
  const repository = normalizeRepository(evidence.repository);
  if (expected.repository && repository.toLowerCase() !== normalizeRepository(expected.repository).toLowerCase()) {
    fail("repository_mismatch", "Preparation artifact repository does not match the operation.");
  }
  if (expected.trustedControllerSha && normalizeSha(evidence.trustedControllerSha) !== normalizeSha(expected.trustedControllerSha)) {
    fail("controller_revision_mismatch", "Preparation artifact was generated by an unexpected controller revision.");
  }
  if (expected.originRunId !== undefined && normalizeRunId(evidence.originRunId) !== normalizeRunId(expected.originRunId)) {
    fail("artifact_provenance_mismatch", "Preparation artifact run ID does not match.");
  }
  const originRunAttempt = normalizeRequiredRunAttempt(evidence.originRunAttempt, "origin workflow run attempt", "artifact_provenance_mismatch");
  if (expected.originRunAttempt !== undefined && originRunAttempt !== normalizeRequiredRunAttempt(expected.originRunAttempt, "expected origin workflow run attempt", "artifact_provenance_mismatch")) {
    fail("artifact_provenance_mismatch", "Preparation artifact run attempt does not match.");
  }
  if (expected.version && parseStableVersion(evidence.version).text !== parseStableVersion(expected.version).text) {
    fail("artifact_identity_mismatch", "Preparation artifact version does not match.");
  }
  normalizeSha(evidence.preparedCommitSha, "prepared commit SHA");
  normalizeSha(evidence.preparedTreeSha, "prepared tree SHA");
  const treeFiles = evidence.expectedTree?.files;
  const expectedTree = Array.isArray(treeFiles)
    ? undefined
    : normalizeExpectedTreeMap(treeFiles);
  const candidateFiles = normalizeCandidateFiles(evidence.candidateFiles ?? (Array.isArray(treeFiles) ? treeFiles : undefined));
  const expectedDigest = normalizeDigest(evidence.expectedTree?.digest, "expected tree digest");
  if (expectedTree) {
    for (const file of candidateFiles) {
      const expected = expectedTree[file.path];
      if (!expected || expected.mode !== file.mode || expected.sha256 !== sha256(file.content)) fail("artifact_digest_mismatch", "Preparation artifact candidate file is inconsistent.", { path: file.path });
    }
  } else if (computeCandidateTreeDigest(candidateFiles) !== expectedDigest) {
    fail("artifact_digest_mismatch", "Preparation artifact tree digest is inconsistent.");
  }
  const notesDigest = jsonDigest(evidence.notesInputSnapshot);
  if (notesDigest !== normalizeDigest(evidence.notesInputDigest, "notes input digest")) fail("artifact_digest_mismatch", "Preparation artifact notes digest is inconsistent.");
  const content = { ...evidence };
  delete content.contentDigest;
  // The transport record is attached after the immutable payload is uploaded
  // so it can contain the provider-assigned artifact ID/digest. It is a
  // locator for the already-authenticated payload, not part of that payload's
  // content digest.
  delete content.artifact;
  if (jsonDigest(content) !== normalizeDigest(evidence.contentDigest, "preparation content digest")) fail("artifact_digest_mismatch", "Preparation artifact content digest is inconsistent.");
  ensureSafeEvidenceValue(evidence, "preparation artifact");
  if (expected.now !== undefined && evidence.expiresAt !== undefined && Date.parse(evidence.expiresAt) <= Number(expected.now)) {
    fail("artifact_expired", "Preparation artifact has expired.");
  }
  return evidence;
}

export function validateArtifactMetadata(metadata, expected = {}, now = Date.now()) {
  const artifact = asObject(metadata, "artifact metadata");
  const id = Number(artifact.id);
  if (!Number.isSafeInteger(id) || id <= 0) fail("artifact_identity_mismatch", "Artifact ID is malformed.");
  if (expected.id !== undefined && id !== Number(expected.id)) fail("artifact_identity_mismatch", "Artifact ID does not match the immutable intent.");
  if (typeof artifact.digest !== "string" || !IMAGE_DIGEST_PATTERN.test(artifact.digest)) {
    fail("artifact_digest_mismatch", "Artifact metadata is missing its provider digest.");
  }
  const digest = normalizeArtifactDigest(artifact.digest, "artifact digest");
  if (expected.digest && digest !== normalizeArtifactDigest(expected.digest, "expected artifact digest")) fail("artifact_digest_mismatch", "Artifact digest does not match the immutable intent.");
  const name = boundedString(artifact.name, "artifact name", 200);
  if (!ARTIFACT_NAME_PATTERN.test(name)) fail("artifact_identity_mismatch", "Artifact name is unsafe.");
  if (expected.name && name !== expected.name) fail("artifact_identity_mismatch", "Artifact name does not match the immutable intent.");
  if (artifact.expired === true) fail("artifact_expired", "Preparation artifact has expired.");
  const expiresAt = Date.parse(artifact.expires_at ?? "");
  if (!Number.isFinite(expiresAt) || expiresAt <= now) fail("artifact_expired", "Preparation artifact expiry is missing or elapsed.");

  // GitHub's artifact REST DTO carries provenance in workflow_run. The
  // controller never accepts a self-declared workflow_run_id or a caller
  // supplied fallback because those values do not establish artifact origin.
  const workflowRun = asObject(artifact.workflow_run, "artifact workflow run");
  const workflowRunId = normalizeRunId(workflowRun.id);
  if (expected.runId !== undefined && workflowRunId !== normalizeRunId(expected.runId)) {
    fail("artifact_provenance_mismatch", "Artifact workflow run does not match the trusted origin run.");
  }
  let workflowRunAttempt;
  if (workflowRun.run_attempt !== undefined) {
    workflowRunAttempt = normalizeRequiredRunAttempt(workflowRun.run_attempt, "artifact workflow run attempt", "artifact_provenance_mismatch");
  } else if (expected.runAttempt !== undefined) {
    fail("artifact_provenance_mismatch", "Artifact workflow run attempt is missing from provider metadata.");
  }
  if (expected.runAttempt !== undefined && workflowRunAttempt !== normalizeRequiredRunAttempt(expected.runAttempt, "expected artifact workflow run attempt", "artifact_provenance_mismatch")) {
    fail("artifact_provenance_mismatch", "Artifact workflow run attempt does not match the trusted origin run.");
  }
  if (expected.repositoryId !== undefined) {
    const repositoryId = normalizePositiveInteger(workflowRun.repository_id, "artifact workflow repository ID");
    const headRepositoryId = normalizePositiveInteger(workflowRun.head_repository_id, "artifact workflow head repository ID");
    if (repositoryId !== normalizePositiveInteger(expected.repositoryId, "expected repository ID") || headRepositoryId !== normalizePositiveInteger(expected.repositoryId, "expected repository ID")) {
      fail("repository_scope_mismatch", "Artifact workflow repository scope does not match the target repository.");
    }
  }
  if (expected.repository) {
    const repository = normalizeRepository(expected.repository);
    const workflowRepository = workflowRun.repository?.full_name ?? workflowRun.repository_full_name;
    if (workflowRepository !== undefined && String(workflowRepository).toLowerCase() !== repository.toLowerCase()) {
      fail("repository_mismatch", "Artifact workflow repository does not match.");
    }
    if (workflowRepository === undefined && expected.repositoryId === undefined) {
      fail("repository_scope_mismatch", "Artifact workflow repository identity is unavailable.");
    }
  }
  const workflowRunHeadSha = normalizeSha(workflowRun.head_sha, "artifact workflow head SHA");
  if (expected.headSha && workflowRunHeadSha !== normalizeSha(expected.headSha, "expected workflow head SHA")) {
    fail("artifact_provenance_mismatch", "Artifact workflow head does not match the trusted operation.");
  }
  return {
    id,
    digest,
    name,
    expiresAt,
    workflowRunId,
    ...(workflowRunAttempt === undefined ? {} : { workflowRunAttempt }),
    workflowRunHeadSha,
    workflowRunRepositoryId: normalizePositiveInteger(workflowRun.repository_id ?? workflowRun.repository?.id, "artifact workflow repository ID"),
    workflowRunHeadRepositoryId: normalizePositiveInteger(workflowRun.head_repository_id ?? workflowRun.head_repository?.id, "artifact workflow head repository ID"),
  };
}

export function buildArtifactRecord(metadata, expected = {}, now = Date.now()) {
  const checked = validateArtifactMetadata(metadata, expected, now);
  return {
    id: checked.id,
    digest: checked.digest,
    name: checked.name,
    expiresAt: new Date(checked.expiresAt).toISOString(),
    retentionDaysRequested: PREPARATION_ARTIFACT_RETENTION_DAYS,
    workflowRunId: checked.workflowRunId,
  };
}

function normalizeCheckpoint(checkpoint, expected) {
  const value = asObject(checkpoint, "checkpoint");
  const checkpointKind = boundedString(value.checkpointKind, "checkpoint kind", 80);
  if (!RELEASE_CHECKPOINT_KINDS.includes(checkpointKind)) {
    fail("checkpoint_kind_invalid", "Checkpoint kind is not an approved immutable checkpoint.", { checkpointKind });
  }
  const result = {
    ...value,
    schemaVersion: RELEASE_AUTOMATION_SCHEMA_VERSION,
    evidenceKind: "release-checkpoint",
    checkpointKind,
    repository: normalizeRepository(value.repository ?? expected.repository),
    operationId: normalizeOperationId(value.operationId ?? expected.operationId),
    attempt: Number(value.attempt ?? expected.attempt),
    preparationArtifactId: Number(value.preparationArtifactId),
    preparationArtifactDigest: normalizeDigest(value.preparationArtifactDigest, "preparation artifact digest"),
    trustedControllerSha: normalizeSha(value.trustedControllerSha ?? expected.trustedControllerSha, "trusted controller SHA"),
    // A checkpoint records the run that produced it, not the preparation's
    // origin run: the artifact is uploaded by the executing run.
    producerRunId: checkpointPositiveInteger(value.producerRunId ?? expected.producerRunId, "checkpoint producing run ID"),
    producerRunAttempt: checkpointPositiveInteger(value.producerRunAttempt ?? expected.producerRunAttempt, "checkpoint producing run attempt"),
    producerControllerSha: checkpointSha(value.producerControllerSha ?? expected.producerControllerSha, "checkpoint producing controller SHA"),
    createdAt: value.createdAt ?? new Date().toISOString(),
  };
  if (!Number.isSafeInteger(result.preparationArtifactId) || result.preparationArtifactId <= 0) fail("checkpoint_invalid", "Checkpoint artifact ID is malformed.");
  if (result.attempt < 1 || result.attempt > MAX_CANDIDATE_ATTEMPTS) fail("checkpoint_invalid", "Checkpoint attempt is outside the allowed bound.");
  assertCheckpointKindFields(result);
  ensureSafeEvidenceValue(result, "checkpoint");
  return { ...result, contentDigest: jsonDigest(result) };
}

export async function persistImmutableCheckpoint(artifacts, checkpoint, expected) {
  if (!artifacts || typeof artifacts.upload !== "function") fail("artifact_writer_unavailable", "Immutable checkpoint writer is unavailable.");
  const normalized = normalizeCheckpoint(checkpoint, expected);
  const name = `${normalized.operationId}-${normalized.checkpointKind}-attempt-${normalized.attempt}`;
  if (!ARTIFACT_NAME_PATTERN.test(name)) fail("artifact_identity_mismatch", "Checkpoint artifact name is unsafe.");
  const metadata = await artifacts.upload({
    name,
    content: `${canonicalJson(normalized)}\n`,
    retentionDays: PREPARATION_ARTIFACT_RETENTION_DAYS,
    overwrite: false,
  });
  // The provider metadata must describe the run that actually uploaded this
  // checkpoint, which is the recorded producing run.
  const record = buildArtifactRecord(metadata, {
    name,
    repository: normalized.repository,
    runId: normalized.producerRunId,
    repositoryId: expected?.repositoryId,
    headSha: normalized.producerControllerSha,
  });
  if (record.workflowRunAttempt !== undefined && record.workflowRunAttempt !== normalized.producerRunAttempt) {
    fail("artifact_provenance_mismatch", "Checkpoint artifact attempt does not match its recorded producing attempt.");
  }
  return { checkpoint: normalized, artifact: record };
}

/**
 * Use the maintained Actions artifact SDK for trusted preparation and
 * checkpoint transport. The SDK, rather than this controller, owns archive
 * creation and extraction. The returned reader accepts only one expected JSON
 * file from the extracted artifact and rejects path surprises.
 */
export async function createActionsArtifactStore({
  client,
  repository,
  workflowRunId,
  token,
  tokenProvider,
  metadataReader,
  temporaryDirectory,
} = {}) {
  let artifactClient = client;
  if (!artifactClient) {
    try {
      const module = await import("@actions/artifact");
      artifactClient = new module.DefaultArtifactClient();
    } catch {
      fail("artifact_sdk_unavailable", "The maintained Actions artifact SDK is unavailable.");
    }
  }
  for (const method of ["uploadArtifact", "downloadArtifact", "getArtifact"]) {
    if (typeof artifactClient[method] !== "function") fail("artifact_sdk_invalid", `Actions artifact SDK lacks ${method}().`);
  }
  const normalizedRepository = normalizeRepository(repository);
  const [owner, name] = normalizedRepository.split("/");
  const numericRunId = normalizeRunId(workflowRunId);
  const root = path.resolve(temporaryDirectory ?? os.tmpdir());
  const tokenSource = typeof tokenProvider === "function"
    ? tokenProvider
    : token === undefined
      ? undefined
      : async () => token;
  function normalizeArtifactFilename(value) {
    const filename = boundedString(value, "artifact evidence filename", 200);
    if (!SAFE_PATH_PATTERN.test(filename) || filename.includes("/")) {
      fail("artifact_path_invalid", "Artifact evidence filename must be one safe file name.");
    }
    return filename;
  }
  async function currentFindBy(runId = numericRunId) {
    const scopedRunId = normalizeRunId(runId);
    if (!tokenSource) return undefined;
    const current = await tokenSource();
    const currentToken = typeof current === "string" ? current : current?.token;
    boundedString(currentToken, "artifact access token", 10_000);
    return {
      token: currentToken,
      workflowRunId: scopedRunId,
      repositoryOwner: owner,
      repositoryName: name,
    };
  }
  async function temporaryArtifactDirectory(prefix) {
    await fsp.mkdir(root, { recursive: true, mode: 0o700 });
    return fsp.mkdtemp(path.join(root, prefix));
  }
  return {
    async upload({ name: artifactName, content, retentionDays = PREPARATION_ARTIFACT_RETENTION_DAYS, overwrite = false } = {}) {
      boundedString(artifactName, "artifact name", 200);
      if (!ARTIFACT_NAME_PATTERN.test(artifactName) || overwrite) fail("artifact_identity_mismatch", "Immutable artifact upload options are unsafe.");
      if (!Number.isSafeInteger(Number(retentionDays)) || Number(retentionDays) < 1 || Number(retentionDays) > PREPARATION_ARTIFACT_RETENTION_DAYS) {
        fail("artifact_retention_invalid", "Artifact retention is outside the supported immutable retention bound.");
      }
      ensureSafeEvidenceValue(content, "artifact content");
      const directory = await temporaryArtifactDirectory("media-finder-release-artifact-");
      const filePath = path.join(directory, "release-evidence.json");
      try {
        await fsp.writeFile(filePath, typeof content === "string" ? content : canonicalJson(content), { encoding: "utf8", mode: 0o600 });
        // v6's maintained SDK takes the root directory as its third argument;
        // `overwrite` is intentionally not a supported option because each
        // evidence/checkpoint name is immutable and unique to one attempt.
        const uploaded = await artifactClient.uploadArtifact(
          artifactName,
          [filePath],
          directory,
          { retentionDays: Number(retentionDays) },
        );
        const uploadedId = uploaded?.id;
        const uploadedDigest = uploaded?.digest ?? uploaded?.artifact_digest;
        const findBy = await currentFindBy();
        const metadataResult = await artifactClient.getArtifact(artifactName, findBy ? { findBy } : undefined);
        let value = asObject(metadataResult?.artifact ?? metadataResult, "uploaded artifact metadata");
        if (uploadedId !== undefined && value.id !== undefined && Number(uploadedId) !== Number(value.id)) {
          fail("artifact_identity_mismatch", "Artifact SDK and metadata IDs do not match.");
        }
        const sdkMetadataDigest = value.digest ?? value.artifact_digest;
        if (uploadedDigest !== undefined && sdkMetadataDigest !== undefined && normalizeArtifactDigest(uploadedDigest, "uploaded artifact digest") !== normalizeArtifactDigest(sdkMetadataDigest, "artifact metadata digest")) {
          fail("artifact_digest_mismatch", "Artifact SDK and metadata digests do not match.");
        }
        const id = value.id ?? uploadedId;
        if (metadataReader) {
          if (!Number.isSafeInteger(Number(id)) || Number(id) <= 0) fail("artifact_identity_mismatch", "Uploaded artifact ID is missing.");
          const restMetadata = await metadataReader(Number(id));
          value = asObject(restMetadata?.artifact ?? restMetadata, "verified artifact metadata");
          if (uploadedId !== undefined && Number(uploadedId) !== Number(value.id)) {
            fail("artifact_identity_mismatch", "Uploaded artifact ID does not match the verified REST metadata.");
          }
          const restMetadataDigest = value.digest ?? value.artifact_digest;
          if (uploadedDigest !== undefined && (restMetadataDigest === undefined || normalizeArtifactDigest(uploadedDigest, "uploaded artifact digest") !== normalizeArtifactDigest(restMetadataDigest, "verified artifact metadata digest"))) {
            fail("artifact_digest_mismatch", "Uploaded artifact digest does not match the verified REST metadata.");
          }
          // Preserve the provider's REST DTO. In particular, the SDK returns
          // a bare SHA-256 hash while the REST metadata uses `sha256:<hash>`;
          // replacing the latter with the SDK value loses the authenticated
          // metadata contract and can make a later validation trust a
          // transport hint instead of the provider record.
          return value;
        }
        return {
          ...value,
          id,
          digest: value.digest ?? value.artifact_digest ?? uploadedDigest,
        };
      } finally {
        await fsp.rm(directory, { recursive: true, force: true });
      }
    },
    async read(id, { digest, expectedFilename = "release-evidence.json", workflowRunId } = {}) {
      const numericId = Number(id);
      if (!Number.isSafeInteger(numericId) || numericId <= 0) fail("artifact_identity_mismatch", "Artifact ID is malformed.");
      // The download must name the run that actually produced the artifact;
      // falling back to a store default could resolve another run's artifact.
      if (workflowRunId === undefined || workflowRunId === null || workflowRunId === "") {
        fail("artifact_provenance_mismatch", "Artifact readback requires the explicit producing workflow run.");
      }
      const filename = normalizeArtifactFilename(expectedFilename);
      const directory = await temporaryArtifactDirectory("media-finder-release-download-");
      try {
        // Resolve the token immediately before each SDK download batch. Long
        // recovery runs may cross the five-minute renewal window.
        const findBy = await currentFindBy(workflowRunId);
        const downloaded = await artifactClient.downloadArtifact(numericId, {
          path: directory,
          ...(findBy ? { findBy } : {}),
          ...(digest !== undefined ? { expectedHash: artifactSdkDigest(digest) } : {}),
        });
        if (downloaded?.digestMismatch === true) fail("artifact_digest_mismatch", "Downloaded immutable artifact digest does not match the recorded digest.");
        if (downloaded?.downloadPath && path.resolve(downloaded.downloadPath) !== path.resolve(directory)) {
          fail("artifact_path_invalid", "Artifact SDK returned an unexpected extraction path.");
        }
        const files = await listRegularFiles(directory);
        if (files.length !== 1 || path.basename(files[0]) !== filename) fail("artifact_path_invalid", "Immutable artifact contains unexpected files.");
        const raw = await fsp.readFile(files[0], "utf8");
        if (Buffer.byteLength(raw, "utf8") > MAX_EVIDENCE_BYTES) fail("evidence_too_large", "Downloaded artifact exceeds the bounded evidence limit.");
        return JSON.parse(raw);
      } catch (error) {
        if (error instanceof ReleaseAutomationError) throw error;
        fail("artifact_download_failed", "Immutable artifact could not be downloaded safely.");
      } finally {
        await fsp.rm(directory, { recursive: true, force: true });
      }
    },
    async metadata(artifactName) {
      boundedString(artifactName, "artifact name", 200);
      if (!ARTIFACT_NAME_PATTERN.test(artifactName)) fail("artifact_identity_mismatch", "Artifact name is unsafe.");
      const findBy = await currentFindBy();
      const value = await artifactClient.getArtifact(artifactName, findBy ? { findBy } : undefined);
      return value?.artifact ?? value;
    },
  };
}

async function listRegularFiles(root) {
  const result = [];
  async function visit(directory) {
    const entries = await fsp.readdir(directory, { withFileTypes: true });
    for (const entry of entries) {
      const target = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) fail("artifact_path_invalid", "Immutable artifact contains a symbolic link.");
      if (entry.isDirectory()) await visit(target);
      else if (entry.isFile()) result.push(target);
      else fail("artifact_path_invalid", "Immutable artifact contains an unsupported path.");
      if (result.length > 10) fail("artifact_path_invalid", "Immutable artifact contains too many files.");
    }
  }
  await visit(root);
  return result;
}

function normalizePrNumber(value) {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number <= 0) fail("identity_mismatch", "Pull request number is malformed.");
  return number;
}

function requiredPullRequestIdentity(value, label) {
  if (typeof value !== "string" || value.length === 0 || value.length > 300) {
    fail("candidate_identity_mismatch", `Release pull request is missing its ${label}.`);
  }
  return value;
}

function pullRequestRepositoryId(value, label) {
  const repository = asObject(value, `release pull request ${label}`);
  const id = Number(repository.id);
  if (!Number.isSafeInteger(id) || id <= 0) {
    fail("candidate_identity_mismatch", `Release pull request is missing its ${label} ID.`);
  }
  return id;
}

/**
 * Mandatory release-PR identity. Every checked identity must be present in the
 * provider response; an omitted field fails closed instead of being replaced by
 * a configured repository name or skipped. The author login must equal the
 * exact `slug[bot]` login of the authenticated installation App; a generic
 * `user.type === "Bot"` never satisfies authorship.
 *
 * The recorded base SHA is an immutable preparation input. An unmerged PR whose
 * live base advanced is no longer the authenticated candidate for that base; it
 * stops as `base_changed` (which the bounded stale-base replacement reconciles)
 * instead of being merged or silently re-based. A merged PR has already passed
 * its merge gate, so only the immutable identities are re-checked there.
 */
function assertPullRequestIdentity(pullRequest, { repositoryId, branch, headSha, baseSha, botLogin, allowStaleBase = false } = {}) {
  const pr = asObject(pullRequest, "release pull request");
  const expectedRepositoryId = normalizePositiveInteger(repositoryId, "expected repository ID");
  const expectedBranch = requiredPullRequestIdentity(branch, "expected release branch");
  const expectedHeadSha = normalizeSha(headSha, "expected pull request head SHA");
  const recordedBaseSha = normalizeSha(baseSha, "recorded base SHA");
  const expectedBotLogin = requiredPullRequestIdentity(botLogin, "authenticated App bot login");

  if (pullRequestRepositoryId(pr.base?.repo, "base repository") !== expectedRepositoryId) {
    fail("candidate_identity_mismatch", "Release PR base repository is not the authenticated release repository.");
  }
  if (pr.base?.ref !== "main") fail("candidate_identity_mismatch", "Release PR does not target main.");
  const observedBaseSha = normalizeSha(requiredPullRequestIdentity(pr.base?.sha, "base SHA"), "pull request base SHA");
  if (pullRequestRepositoryId(pr.head?.repo, "head repository") !== expectedRepositoryId) {
    fail("candidate_identity_mismatch", "Release PR head repository is not the authenticated release repository.");
  }
  if (pr.head?.ref !== expectedBranch) {
    fail("candidate_identity_mismatch", "Release PR head branch is not the generated release branch.");
  }
  if (normalizeSha(requiredPullRequestIdentity(pr.head?.sha, "head SHA"), "pull request head SHA") !== expectedHeadSha) {
    fail("candidate_identity_mismatch", "Release PR head is not the prepared candidate commit.");
  }
  const author = pr.user;
  if (author === null || typeof author !== "object" || Array.isArray(author)) {
    fail("candidate_identity_mismatch", "Release pull request is missing its author identity.");
  }
  if (author.type !== "Bot") fail("candidate_identity_mismatch", "Release PR was not created by a bot account.");
  const authorLogin = requiredPullRequestIdentity(author.login, "author login");
  if (authorLogin.toLowerCase() !== expectedBotLogin.toLowerCase()) {
    fail("candidate_identity_mismatch", "Release PR author is not the authenticated installation App.", {
      expectedAuthor: expectedBotLogin,
      observedAuthor: authorLogin,
    });
  }
  const merged = pr.merged === true || Boolean(pr.merged_at);
  // `allowStaleBase` is used only to inspect a candidate that is already known
  // to be stale (base advanced past its recorded base). The base field is still
  // mandatory; only the equality to the recorded base is deferred to the caller.
  if (!allowStaleBase && !merged && observedBaseSha !== recordedBaseSha) {
    fail("base_changed", "Release PR base advanced past the recorded preparation base; reconcile the stale candidate before merge.", {
      recordedBaseSha,
      observedBaseSha,
    });
  }
  return { merged, observedBaseSha };
}

/**
 * Reconcile an uncertain `createPullRequest` against live provider state.
 *
 * A pull request that already carries the generated branch, the prepared head,
 * the recorded base, the authenticated repository and the exact App author is
 * adopted. Any other pull request that claims the branch is a conflict: the
 * controller stops without closing, editing, labelling or force-pushing it.
 */
async function findMatchingReleasePullRequest(api, auth, { state, branch, repositoryId, botLogin } = {}) {
  if (typeof api?.listPullRequests !== "function" || typeof api?.getPullRequest !== "function") {
    fail("pull_request_reconciliation_unavailable", "Live pull request state is required to reconcile an uncertain creation.");
  }
  const response = await apiCall(api, auth, "listPullRequests", [{ state: "open", base: "main" }]);
  const listed = collectionItems(response, "pulls", "open pull requests")
    .map((item) => asObject(item, "open pull request"))
    .filter((item) => item.head?.ref === branch);
  if (listed.length > 1) fail("mutation_ambiguous", "Multiple open pull requests claim the generated release branch.");
  if (listed.length === 0) return undefined;
  const number = normalizePrNumber(listed[0].number);
  const pullRequest = asObject(await apiCall(api, auth, "getPullRequest", [number]), "release pull request");
  assertPullRequestIdentity(pullRequest, {
    repositoryId,
    branch,
    headSha: state.preparedCommitSha,
    baseSha: state.baseSha,
    botLogin,
  });
  return { ...pullRequest, number };
}

/**
 * Read the live pull request for a generated release branch in any state.
 * Used to reconcile a candidate whose recorded base is no longer current main:
 * a missing or already closed pull request means the earlier attempt was
 * already dispositioned, while an open one is closed only after its terminal
 * disposition is persisted.
 */
async function readReleasePullRequestByBranch(api, auth, branch) {
  if (typeof api?.listPullRequests !== "function" || typeof api?.getPullRequest !== "function") {
    fail("pull_request_reconciliation_unavailable", "Live pull request state is required to reconcile the release candidate.");
  }
  const response = await apiCall(api, auth, "listPullRequests", [{ state: "all", base: "main" }]);
  const listed = collectionItems(response, "pulls", "release pull requests")
    .map((item) => asObject(item, "release pull request"))
    .filter((item) => item.head?.ref === branch);
  if (listed.length > 1) fail("mutation_ambiguous", "Multiple pull requests claim the generated release branch.");
  if (listed.length === 0) return undefined;
  const number = normalizePrNumber(listed[0].number);
  const pullRequest = asObject(await apiCall(api, auth, "getPullRequest", [number]), "release pull request");
  return { ...pullRequest, number };
}

/** The run identity that produces a checkpoint written by this execution. */
function producerIdentity(context, config) {
  return {
    producerRunId: context.runId,
    producerRunAttempt: context.runAttempt,
    producerControllerSha: normalizeSha(config.trustedControllerSha ?? context.sha, "producing controller SHA"),
  };
}

/** Persist the terminal stale-attempt disposition before anything is closed. */
/**
 * Persist the terminal stale-attempt disposition before anything is closed.
 * An already-recorded disposition for this attempt is reused instead of being
 * written twice: the artifact name is immutable, so a rerun after a crash
 * between the disposition and the close must not collide with it.
 */
async function persistStaleDisposition({ artifacts, evidence, artifact, prNumber, currentMainSha, producer, recorded }) {
  if (recorded !== undefined) return recorded.artifact;
  if (!artifacts || typeof artifacts.upload !== "function") {
    fail("checkpoint_writer_unavailable", "A stale candidate cannot be closed without durable immutable disposition evidence.");
  }
  const checkpoint = await persistImmutableCheckpoint(artifacts, {
    checkpointKind: "stale-base",
    repository: evidence.repository,
    operationId: evidence.operationId,
    attempt: evidence.attempt,
    preparationArtifactId: artifact.id,
    preparationArtifactDigest: artifact.digest,
    trustedControllerSha: evidence.trustedControllerSha,
    ...(prNumber === undefined ? {} : { prNumber }),
    prHeadSha: evidence.preparedCommitSha,
    prBaseSha: evidence.baseSha,
    disposition: "terminal_stale_base",
    currentMainSha,
    ...producer,
  }, { ...evidence, artifact });
  return checkpoint.artifact;
}

function normalizedCheckName(value) {
  return String(value ?? "").toLowerCase().replace(/\s+/g, " ").trim();
}

// Candidate paths are ASCII-safe, so code-unit ordering is the same ordering
// used by the preparer's Python `sorted()` when constructing tree digests.
function compareSafePaths(left, right) {
  return left < right ? -1 : left > right ? 1 : 0;
}

function checkContextMatches(name, expected) {
  const normalized = normalizedCheckName(name);
  const target = normalizedCheckName(expected);
  const leaf = target.split(" / ").at(-1);
  // Protected check contexts are matched exactly. Reusable-workflow jobs use
  // the leaf job name, but they are accepted only after being tied to the
  // selected run/attempt/head and check-run URL below.
  return normalized === target || normalized === leaf;
}

function asArray(value, label) {
  if (!Array.isArray(value)) fail("malformed_response", `${label} must be an array.`);
  return value;
}

function assertCompleteCollection(container, items, label) {
  if (container && typeof container === "object" && !Array.isArray(container)) {
    if (container.incomplete_results === true) fail("pagination_incomplete", `${label} response is incomplete.`);
    if (container.total_count !== undefined) {
      const total = Number(container.total_count);
      if (!Number.isSafeInteger(total) || total < items.length || total > items.length) {
        fail("pagination_incomplete", `${label} response did not contain the complete result set.`);
      }
    }
  }
}

async function invoke(api, method, args = []) {
  if (!api || typeof api[method] !== "function") fail("adapter_unavailable", `GitHub adapter does not implement ${method}.`);
  return api[method](...args);
}

async function ensureApiAuth(auth) {
  if (auth && typeof auth.ensureToken === "function") await auth.ensureToken();
}

async function apiCall(api, auth, method, args = []) {
  await ensureApiAuth(auth);
  return invoke(api, method, args);
}

async function validateInitiatingActor(api, auth, actor) {
  if (typeof api?.getCollaboratorPermission !== "function") {
    fail("actor_permission_unavailable", "Initiating actor permission evidence is unavailable.");
  }
  const permission = await apiCall(api, auth, "getCollaboratorPermission", [actor]);
  if (!new Set(["admin", "maintain", "push", "write"]).has(String(permission.permission ?? "").toLowerCase())) {
    fail("unauthorized_actor", "Initiating actor is not a repository writer.");
  }
}

// A mutation whose response was never received may still have been applied.
// These failures are therefore "post-mutation transport failures": the caller
// must read live provider state before retrying instead of blindly repeating or
// reporting the request as not applied.
const POST_MUTATION_TRANSPORT_CODES = new Set([
  "token_expired",
  "github_unavailable",
  "response_too_large",
  "malformed_response",
]);

function isPostMutationTransportFailure(error) {
  if (!(error instanceof ReleaseAutomationError)) return false;
  if (POST_MUTATION_TRANSPORT_CODES.has(error.code)) return true;
  return error.code === "github_api_error" && Number(error.details?.status) >= 500;
}

async function mutationWithReconcile(api, auth, mutation, reconcile) {
  await ensureApiAuth(auth);
  let retried = false;
  for (;;) {
    try {
      return await mutation();
    } catch (error) {
      if (!isPostMutationTransportFailure(error)) throw error;
      const observed = await reconcile();
      if (observed?.completed) return observed.value;
      if (observed?.ambiguous) fail("mutation_ambiguous", "Mutation outcome is ambiguous after a transport failure; resume after reconciling state.");
      if (retried) fail("mutation_ambiguous", "Mutation could not be confirmed after reconciling live state.", { code: error.code });
      retried = true;
      await ensureApiAuth(auth);
    }
  }
}

function normalizeClock(clock = {}) {
  return {
    now: typeof clock.now === "function" ? clock.now : () => Date.now(),
    sleep: typeof clock.sleep === "function" ? clock.sleep : (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds)),
  };
}

/**
 * One deadline for the whole release operation.
 *
 * The hosted workflow job has a hard limit, so the controller assigns a single
 * budget below it once and every bounded wait consumes from that same budget
 * instead of restarting a fresh per-call deadline. Expiry stops the operation
 * with the completed boundary so a re-dispatch can resume from the immutable
 * preparation/checkpoint records.
 */
export function createOperationBudget({ clock = normalizeClock(), deadlineMs = DEFAULT_OPERATION_DEADLINE_MS } = {}) {
  const configured = Number(deadlineMs);
  if (!Number.isSafeInteger(configured) || configured <= 0) {
    fail("operation_deadline_invalid", "The operation deadline must be a positive whole number of milliseconds.");
  }
  if (configured > MAX_OPERATION_DEADLINE_MS) {
    fail("operation_deadline_invalid", "The operation deadline must stay below the hosted workflow job limit.", {
      deadlineMs: configured,
      bound: MAX_OPERATION_DEADLINE_MS,
    });
  }
  const normalizedClock = normalizeClock(clock);
  const deadlineAt = normalizedClock.now() + configured;
  const budget = {
    deadlineMs: configured,
    deadlineAt,
    clock: normalizedClock,
    remaining(label = "operation") {
      const remaining = deadlineAt - normalizedClock.now();
      if (remaining <= 0) budget.expire(label);
      return remaining;
    },
    expire(label = "operation") {
      const completedBoundary = typeof budget.boundaryProbe === "function" ? budget.boundaryProbe() : undefined;
      fail("operation_deadline_exceeded", "The operation-wide release deadline elapsed; resume from the immutable recovery state.", {
        label,
        deadlineMs: configured,
        deadlineAt: new Date(deadlineAt).toISOString(),
        ...(completedBoundary === undefined ? {} : { completedBoundary }),
      });
    },
    watch(boundaryProbe) {
      budget.boundaryProbe = boundaryProbe;
      return budget;
    },
  };
  return budget;
}

async function pollUntil(probe, {
  clock = normalizeClock(),
  budget,
  deadlineMs = budget === undefined ? DEFAULT_OPERATION_DEADLINE_MS : undefined,
  label = "operation",
  maxPolls = 1000,
} = {}) {
  const start = clock.now();
  let delay = 1000;
  for (let poll = 0; poll < maxPolls; poll += 1) {
    const result = await probe();
    if (result?.state === "passed" || result?.state === "failed" || result?.state === "stale" || result?.state === "untrusted") return result;
    const budgetRemaining = budget === undefined ? Number.POSITIVE_INFINITY : budget.remaining(label);
    const callRemaining = deadlineMs === undefined ? Number.POSITIVE_INFINITY : deadlineMs - (clock.now() - start);
    const remaining = Math.min(budgetRemaining, callRemaining);
    if (remaining <= 0) {
      if (budget !== undefined) budget.expire(label);
      fail("timeout", `${label} exceeded its bounded deadline; resume from immutable state.`, { deadlineMs });
    }
    await clock.sleep(Math.min(delay, MAX_POLL_DELAY_MS, remaining));
    delay = Math.min(delay * 2, MAX_POLL_DELAY_MS);
  }
  fail("timeout", `${label} exceeded its bounded poll count; resume from immutable state.`, { maxPolls });
}

function collectionItems(value, key, label) {
  if (Array.isArray(value)) return value;
  const container = asObject(value, label);
  const items = asArray(container[key], label);
  assertCompleteCollection(container, items, label);
  return items;
}

function normalizedWorkflowPath(value, label) {
  if (typeof value !== "string" || value.length === 0 || value.length > 300) {
    fail("malformed_response", `${label} is missing or malformed.`);
  }
  return value;
}

function workflowPathMatches(value, expectedPath, event, headBranch, repository) {
  const actual = normalizedWorkflowPath(value, "workflow path");
  if (actual === expectedPath) return true;
  // The workflow-run REST DTO may include the repository prefix and an @ref
  // qualifier (for example owner/repo/.github/workflows/ci.yaml@main). Only
  // the exact configured repository, workflow file and approved main ref are
  // accepted; arbitrary suffixes or foreign workflow paths remain untrusted.
  if (actual === `${expectedPath}@main`) return ["push", "release", "workflow_dispatch"].includes(event) && headBranch === "main";
  if (!repository) return false;
  const repositoryPrefix = `${normalizeRepository(repository)}/`;
  return actual.slice(0, repositoryPrefix.length).toLowerCase() === repositoryPrefix.toLowerCase() &&
    actual.slice(repositoryPrefix.length) === `${expectedPath}@main`;
}

function workflowRepositoryMatches(run, { repository, repositoryId } = {}) {
  const expectedRepository = repository ? normalizeRepository(repository).toLowerCase() : undefined;
  const nestedRepository = run.repository?.full_name ?? run.repository_full_name;
  if (expectedRepository && nestedRepository !== undefined && String(nestedRepository).toLowerCase() !== expectedRepository) return false;
  const actualRepositoryId = run.repository_id ?? run.repository?.id;
  const actualHeadRepositoryId = run.head_repository_id ?? run.head_repository?.id;
  if (repositoryId !== undefined) {
    const expectedId = normalizePositiveInteger(repositoryId, "repository ID");
    if (Number(actualRepositoryId) !== expectedId || Number(actualHeadRepositoryId) !== expectedId) return false;
  } else if (nestedRepository === undefined || actualHeadRepositoryId === undefined) {
    return false;
  }
  const nestedHeadRepository = run.head_repository?.full_name;
  if (expectedRepository && nestedHeadRepository !== undefined && String(nestedHeadRepository).toLowerCase() !== expectedRepository) return false;
  return true;
}

function assertWorkflowRunIdentity(run, {
  headSha,
  repository,
  repositoryId,
  event,
  workflowPath,
  requireMainBranch = false,
  requireRunAttempt = false,
} = {}) {
  const value = asObject(run, "workflow run");
  if (String(value.event ?? "") !== event) fail("untrusted_workflow", `Workflow run event is not ${event}.`);
  const headBranch = value.head_branch ?? value.branch;
  if (!workflowPathMatches(value.path, workflowPath, event, headBranch, repository)) fail("untrusted_workflow", `Workflow run path is not ${workflowPath}.`);
  if (String(value.head_sha ?? "").toLowerCase() !== normalizeSha(headSha, "workflow run head SHA")) {
    fail("untrusted_workflow", "Workflow run head does not match the candidate.");
  }
  if (!workflowRepositoryMatches(value, { repository, repositoryId })) {
    fail("untrusted_workflow", "Workflow run repository identity is not trusted.");
  }
  if (requireMainBranch && headBranch !== "main") fail("untrusted_workflow", "Main publication workflow run is not for the main branch.");
  const runAttempt = requireRunAttempt
    ? normalizeRequiredRunAttempt(value.run_attempt, "workflow run attempt", "untrusted_workflow")
    : normalizeRunAttempt(value.run_attempt);
  const runId = normalizeRunId(value.id);
  return { value, runId, runAttempt };
}

function authenticatedAppIdentity(auth, repository, expectedRepositoryId) {
  const identity = asObject(auth?.current?.identity, "authenticated App identity");
  const appId = normalizePositiveInteger(identity.appId, "authenticated App ID");
  const installationId = normalizePositiveInteger(identity.installationId, "authenticated installation ID");
  const repositoryId = normalizePositiveInteger(identity.repositoryId, "authenticated repository ID");
  if (String(identity.repository ?? "").toLowerCase() !== normalizeRepository(repository).toLowerCase()) {
    fail("repository_scope_mismatch", "Authenticated App identity is scoped to a different repository.");
  }
  if (expectedRepositoryId !== undefined && repositoryId !== normalizePositiveInteger(expectedRepositoryId, "expected repository ID")) {
    fail("repository_scope_mismatch", "Authenticated App identity repository ID does not match the release target.");
  }
  return { appId, installationId, repositoryId, repository: normalizeRepository(repository), appSlug: identity.appSlug };
}

/**
 * The exact GitHub login an App-authored pull request carries. A missing or
 * malformed authenticated slug is a hard failure: PR authorship is an identity
 * gate, not a best-effort hint, and a generic `Bot` type never satisfies it.
 */
function appBotLogin(identity) {
  const slug = asObject(identity, "authenticated App identity").appSlug;
  if (typeof slug !== "string" || !/^[A-Za-z0-9-]{1,200}$/.test(slug)) {
    fail("app_identity_mismatch", "The authenticated App bot login is unavailable.");
  }
  return `${slug}[bot]`;
}

function workflowActorLogin(run) {
  const actor = asObject(run.actor, "original workflow actor");
  return boundedString(actor.login, "original workflow actor login", 100);
}

function assertAllowedActor(actor, allowedActors = []) {
  const allowed = allowedActors.map((value) => String(value).trim().toLowerCase()).filter(Boolean);
  if (allowed.length > 0 && !allowed.includes(actor.toLowerCase())) {
    fail("unauthorized_actor", "Original workflow actor is not an allowed repository writer.");
  }
}

function assertPreparationRunRepository(run, repository, repositoryId) {
  const value = asObject(run, "original workflow run");
  const expectedRepository = normalizeRepository(repository).toLowerCase();
  const expectedRepositoryId = normalizePositiveInteger(repositoryId, "expected repository ID");
  const actualRepositoryId = normalizePositiveInteger(value.repository_id ?? value.repository?.id, "original workflow repository ID");
  const actualHeadRepositoryId = normalizePositiveInteger(value.head_repository_id ?? value.head_repository?.id, "original workflow head repository ID");
  if (actualRepositoryId !== expectedRepositoryId || actualHeadRepositoryId !== expectedRepositoryId) {
    fail("untrusted_workflow", "Original workflow run repository scope is not the release repository.");
  }
  const repositoryName = value.repository?.full_name ?? value.repository_full_name;
  const headRepositoryName = value.head_repository?.full_name ?? value.head_repository_full_name;
  if (repositoryName === undefined || headRepositoryName === undefined ||
      String(repositoryName).toLowerCase() !== expectedRepository ||
      String(headRepositoryName).toLowerCase() !== expectedRepository) {
    fail("untrusted_workflow", "Original workflow run repository names are incomplete or foreign.");
  }
}

async function authenticatePreparationRun(api, auth, listedRun, {
  repository,
  repositoryId,
  allowedActors = [],
  runAttempt,
} = {}) {
  const listed = asObject(listedRun, "preparation workflow run listing");
  const runId = normalizeRunId(listed.id);
  const selectedAttempt = normalizeRequiredRunAttempt(
    runAttempt ?? listed.run_attempt,
    "preparation workflow run attempt",
    "untrusted_workflow",
  );
  if (typeof api?.getWorkflowRunAttempt !== "function") {
    fail("origin_run_unavailable", "The attempt-specific preparation workflow run endpoint is unavailable.");
  }
  const actual = asObject(
    await apiCall(api, auth, "getWorkflowRunAttempt", [runId, selectedAttempt]),
    "preparation workflow run attempt",
  );
  const actualRunId = normalizeRunId(actual.id);
  const actualAttempt = normalizeRequiredRunAttempt(actual.run_attempt, "preparation workflow run attempt", "untrusted_workflow");
  if (actualRunId !== runId || actualAttempt !== selectedAttempt) {
    fail("untrusted_workflow", "Attempt-specific preparation workflow metadata does not match the listed run.");
  }
  const identity = assertWorkflowRunIdentity(actual, {
    headSha: actual.head_sha,
    repository,
    repositoryId,
    event: "workflow_dispatch",
    workflowPath: PREPARATION_WORKFLOW_PATH,
    requireMainBranch: true,
    requireRunAttempt: true,
  });
  assertPreparationRunRepository(actual, repository, repositoryId);
  const actor = workflowActorLogin(actual);
  assertAllowedActor(actor, allowedActors);
  await validateInitiatingActor(api, auth, actor);
  return {
    value: identity.value,
    runId: identity.runId,
    runAttempt: identity.runAttempt,
    headSha: normalizeSha(actual.head_sha, "original controller SHA"),
    actor,
  };
}

function releaseArtifactName(value) {
  if (typeof value !== "string" || value.length > 200) return undefined;
  const match = value.match(/^((?:release-[a-z0-9-]{1,80}))-(preparation|pr-created|stale-base|merged)-attempt-([1-9][0-9]*)$/);
  if (!match) return undefined;
  const attempt = Number(match[3]);
  if (!Number.isSafeInteger(attempt) || attempt < 1 || attempt > MAX_CANDIDATE_ATTEMPTS) return undefined;
  return { operationId: match[1], kind: match[2], attempt, name: value };
}

function checkpointPositiveInteger(value, label) {
  const numeric = Number(value);
  if (!Number.isSafeInteger(numeric) || numeric <= 0) fail("checkpoint_invalid", `${label} is malformed.`);
  return numeric;
}

function checkpointSha(value, label) {
  if (typeof value !== "string" || !SHA_PATTERN.test(value)) fail("checkpoint_invalid", `${label} must be a 40-character Git SHA.`);
  return value.toLowerCase();
}

function assertCheckpointKindFields(record) {
  const label = `Checkpoint kind ${record.checkpointKind}`;
  if (!RELEASE_CHECKPOINT_KINDS.includes(record.checkpointKind)) {
    fail("checkpoint_kind_invalid", "Checkpoint kind is not an approved immutable checkpoint.", {
      checkpointKind: record.checkpointKind,
    });
  }
  checkpointPositiveInteger(record.prNumber, `${label} pull request number`);
  checkpointSha(record.prHeadSha, `${label} head SHA`);
  checkpointSha(record.prBaseSha, `${label} base SHA`);
  if (record.checkpointKind === "stale-base") {
    if (record.disposition !== "terminal_stale_base") {
      fail("checkpoint_invalid", "A stale-attempt checkpoint must record its terminal disposition.");
    }
    checkpointSha(record.currentMainSha, `${label} current main SHA`);
  }
  if (record.checkpointKind === "merged") {
    checkpointSha(record.mergedSha, `${label} merged SHA`);
  }
}

/**
 * Validate one immutable checkpoint record. Every checked identity must be
 * present; a record whose content digest, chain link, producing run or kind
 * does not match is refused instead of being trusted from its artifact name.
 */
export function assertCheckpointRecord(value, expected = {}) {
  const record = asObject(value, "checkpoint record");
  if (record.schemaVersion !== RELEASE_AUTOMATION_SCHEMA_VERSION || record.evidenceKind !== "release-checkpoint") {
    fail("checkpoint_invalid", "Checkpoint record schema is unsupported.");
  }
  const repository = normalizeRepository(record.repository);
  if (expected.repository && repository.toLowerCase() !== normalizeRepository(expected.repository).toLowerCase()) {
    fail("repository_mismatch", "Checkpoint record repository does not match the operation.");
  }
  const operationId = normalizeOperationId(record.operationId);
  if (expected.operationId !== undefined && operationId !== normalizeOperationId(expected.operationId)) {
    fail("checkpoint_invalid", "Checkpoint record operation does not match.");
  }
  const attempt = Number(record.attempt);
  if (!Number.isSafeInteger(attempt) || attempt < 1 || attempt > MAX_CANDIDATE_ATTEMPTS) {
    fail("checkpoint_invalid", "Checkpoint attempt is outside the allowed bound.");
  }
  if (expected.attempt !== undefined && attempt !== Number(expected.attempt)) {
    fail("checkpoint_invalid", "Checkpoint attempt does not match.");
  }
  const preparationArtifactId = Number(record.preparationArtifactId);
  if (!Number.isSafeInteger(preparationArtifactId) || preparationArtifactId <= 0) {
    fail("checkpoint_invalid", "Checkpoint chain link to the preparation artifact is missing.");
  }
  if (expected.preparationArtifactId !== undefined && preparationArtifactId !== Number(expected.preparationArtifactId)) {
    fail("checkpoint_invalid", "Checkpoint chain link does not match the preparation artifact.");
  }
  if (typeof record.preparationArtifactDigest !== "string" || !DIGEST_PATTERN.test(record.preparationArtifactDigest)) {
    fail("checkpoint_invalid", "Checkpoint chain link to the preparation artifact digest is missing or malformed.");
  }
  const preparationArtifactDigest = record.preparationArtifactDigest.toLowerCase();
  if (expected.preparationArtifactDigest !== undefined && preparationArtifactDigest !== normalizeArtifactDigest(expected.preparationArtifactDigest, "expected preparation artifact digest")) {
    fail("checkpoint_invalid", "Checkpoint chain digest does not match the preparation artifact.");
  }
  checkpointSha(record.trustedControllerSha, "checkpoint trusted controller SHA");
  const producerRunId = checkpointPositiveInteger(record.producerRunId, "Checkpoint producing run ID");
  if (expected.producerRunId !== undefined && producerRunId !== Number(expected.producerRunId)) {
    fail("checkpoint_invalid", "Checkpoint producing run does not match.");
  }
  const producerRunAttempt = checkpointPositiveInteger(record.producerRunAttempt, "Checkpoint producing run attempt");
  if (expected.producerRunAttempt !== undefined && producerRunAttempt !== Number(expected.producerRunAttempt)) {
    fail("checkpoint_invalid", "Checkpoint producing run attempt does not match.");
  }
  const producerControllerSha = checkpointSha(record.producerControllerSha, "Checkpoint producing controller SHA");
  if (expected.producerControllerSha !== undefined && producerControllerSha !== normalizeSha(expected.producerControllerSha, "expected producing controller SHA")) {
    fail("checkpoint_invalid", "Checkpoint producing controller revision does not match.");
  }
  assertCheckpointKindFields({ ...record, checkpointKind: boundedString(record.checkpointKind, "checkpoint kind", 80), prNumber: record.prNumber, prHeadSha: record.prHeadSha, prBaseSha: record.prBaseSha, mergedSha: record.mergedSha, currentMainSha: record.currentMainSha, disposition: record.disposition });
  const content = { ...record };
  delete content.contentDigest;
  delete content.artifact;
  if (typeof record.contentDigest !== "string" || !DIGEST_PATTERN.test(record.contentDigest)) {
    fail("checkpoint_invalid", "Checkpoint content digest is missing or malformed.");
  }
  if (jsonDigest(content) !== record.contentDigest.toLowerCase()) {
    fail("checkpoint_invalid", "Checkpoint content digest is inconsistent.");
  }
  ensureSafeEvidenceValue(record, "checkpoint record");
  if (expected.now !== undefined && record.expiresAt !== undefined && Date.parse(record.expiresAt) <= Number(expected.now)) {
    fail("artifact_expired", "Checkpoint record has expired.");
  }
  return record;
}

function decodedArtifactValue(value) {
  if (Buffer.isBuffer(value)) {
    if (value.length > MAX_EVIDENCE_BYTES) fail("evidence_too_large", "Downloaded preparation evidence exceeds the bounded size limit.");
    try {
      return JSON.parse(value.toString("utf8"));
    } catch {
      fail("artifact_schema_invalid", "Downloaded preparation evidence is not valid JSON.");
    }
  }
  if (typeof value === "string") {
    if (Buffer.byteLength(value, "utf8") > MAX_EVIDENCE_BYTES) fail("evidence_too_large", "Downloaded preparation evidence exceeds the bounded size limit.");
    try {
      return JSON.parse(value);
    } catch {
      fail("artifact_schema_invalid", "Downloaded preparation evidence is not valid JSON.");
    }
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail("artifact_schema_invalid", "Downloaded preparation evidence must be a JSON object.");
  }
  ensureBoundedJson(value, "downloaded preparation evidence");
  return value;
}

function assertPreparationAppIdentity(evidence, identity) {
  if (normalizePositiveInteger(evidence.repositoryId, "preparation repository ID") !== identity.repositoryId) {
    fail("repository_scope_mismatch", "Preparation evidence repository ID does not match the authenticated App.");
  }
  if (normalizePositiveInteger(evidence.appId, "preparation App ID") !== identity.appId) {
    fail("app_identity_mismatch", "Preparation evidence App ID does not match the authenticated App.");
  }
  if (normalizePositiveInteger(evidence.installationId, "preparation installation ID") !== identity.installationId) {
    fail("installation_mismatch", "Preparation evidence installation ID does not match the authenticated installation.");
  }
}

const RELEASE_BRANCH_PATTERN = /^release-[a-z0-9-]+-v((?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))-attempt-[1-9][0-9]*$/;

function releaseVersionFromRef(ref) {
  if (typeof ref !== "string") return undefined;
  const match = ref.match(RELEASE_BRANCH_PATTERN);
  return match === null ? undefined : match[1];
}

function branchCarriesVersion(ref, version) {
  return releaseVersionFromRef(ref) === version;
}

/**
 * Serialize release requests: no release-shaped state may exist for the
 * requested version, and no *other* version may be active at the same time. A
 * second active version is refused before preparation so out-of-order
 * publication cannot be started.
 */
async function assertNoConflictingVersionState(api, auth, version, { repository } = {}) {
  const conflicts = [];
  const active = [];
  const record = (kind, ref, number) => {
    const refVersion = releaseVersionFromRef(ref);
    if (refVersion === undefined) return;
    if (refVersion === version) {
      conflicts.push({ kind, ref, ...(number === undefined ? {} : { number }) });
    } else {
      active.push({ kind, ref, version: refVersion, ...(number === undefined ? {} : { number }) });
    }
  };
  if (typeof api?.listPullRequests === "function") {
    const response = await apiCall(api, auth, "listPullRequests", [{ state: "all", base: "main" }]);
    const pulls = collectionItems(response, "pulls", "release pull requests");
    for (const pull of pulls) {
      const value = asObject(pull, "release pull request");
      record("pull_request", value.head?.ref, value.number);
    }
  }
  if (typeof api?.listBranches === "function") {
    const response = await apiCall(api, auth, "listBranches", []);
    const branches = collectionItems(response, "branches", "release branches");
    for (const branch of branches) {
      const value = asObject(branch, "release branch");
      record("branch", value.name);
    }
  }
  if (conflicts.length > 0) {
    fail("duplicate_release_state", "Release-shaped repository state already exists for the requested version.", {
      repository,
      version,
      conflicts,
    });
  }
  if (active.length > 0) {
    fail("concurrent_release", "Another stable release operation is active.", {
      repository,
      version,
      active,
    });
  }
}

/**
 * Authenticate every immutable preparation artifact this version has ever
 * produced from trusted workflow history. The caller's dispatch run is
 * deliberately not used as the origin: a later trusted controller recovers the
 * original run and downloads its artifact through the provider's actual ID,
 * digest, expiry, and producing run ID.
 *
 * The attempt number is durable here: each preparation attempt is one uniquely
 * named immutable artifact, so a rerun cannot reset the bounded attempt count.
 */
async function collectPreparationCandidates({
  api,
  auth,
  artifacts,
  context,
  version,
  repository,
  repositoryId,
  allowedActors = [],
  now = Date.now(),
} = {}) {
  const requestedVersion = parseStableVersion(version, "requested version").text;
  const targetRepository = normalizeRepository(repository ?? context?.repository);
  const identity = authenticatedAppIdentity(auth, targetRepository, repositoryId);
  const targetRepositoryId = identity.repositoryId;
  if (typeof api?.getWorkflowRuns !== "function" || typeof api?.listRunArtifacts !== "function") {
    fail("discovery_unavailable", "Trusted preparation workflow and artifact listing endpoints are unavailable.");
  }
  if (!artifacts || typeof artifacts.read !== "function") {
    fail("artifact_reader_unavailable", "Immutable preparation artifact reader is unavailable.");
  }
  const runsResponse = await apiCall(api, auth, "getWorkflowRuns", [{
    workflow: PREPARATION_WORKFLOW_PATH,
    event: "workflow_dispatch",
    branch: "main",
  }]);
  const runs = collectionItems(runsResponse, "workflow_runs", "preparation workflow runs");
  const candidates = [];
  const checkpoints = [];
  let firstFailure;

  for (const listedRun of runs) {
    let listedRunId;
    try {
      // The listing is only a bounded locator. Do not authenticate or select
      // its reported/latest attempt: a rerun can expose the original
      // attempt's immutable artifact under the same run ID. The payload's
      // claimed origin attempt is authenticated below after provider metadata
      // and bytes have been located.
      listedRunId = normalizeRunId(asObject(listedRun, "preparation workflow run listing").id);
    } catch (error) {
      firstFailure ??= error;
      continue;
    }
    let artifactResponse;
    try {
      artifactResponse = await apiCall(api, auth, "listRunArtifacts", [listedRunId]);
    } catch (error) {
      firstFailure ??= error;
      continue;
    }
    const artifactHints = collectionItems(artifactResponse, "artifacts", "preparation workflow artifacts")
      .map((item) => asObject(item, "release artifact listing"))
      .map((item) => ({ item, parsed: releaseArtifactName(item.name) }))
      .filter(({ parsed }) => parsed !== undefined);
    for (const { item: hint, parsed: nameParts } of artifactHints) {
      // Names are locators, never authority. They still provide a bounded
      // way to retain a useful failure for this requested version: generated
      // preparation names are deterministic from repository, version, and
      // producing run ID. An expired or malformed artifact for an unrelated
      // historical version must not block a fresh request.
      const deterministicName = nameParts.operationId === operationIdFor({
        repository: targetRepository,
        version: requestedVersion,
        originRunId: listedRunId,
      }) || candidates.some(({ evidence }) => evidence.operationId === nameParts.operationId);
      let metadata;
      let record;
      let downloaded;
      let payload;
      try {
        const artifactId = normalizePositiveInteger(hint.id, "preparation artifact ID");
        metadata = asObject(await apiCall(api, auth, "getArtifact", [artifactId]), "preparation artifact metadata");
        record = validateArtifactMetadata(metadata, {
          id: artifactId,
          ...(hint.digest === undefined ? {} : { digest: hint.digest }),
          name: nameParts.name,
          runId: listedRunId,
          repository: targetRepository,
          repositoryId: targetRepositoryId,
        }, now);
        downloaded = await artifacts.read(record.id, {
          digest: record.digest,
          expectedFilename: "release-evidence.json",
          workflowRunId: record.workflowRunId,
        });
        payload = decodedArtifactValue(downloaded);
      } catch (error) {
        // Retain validation failures only for a deterministic hint for the
        // requested version. The hint still cannot grant authority or bypass
        // a later payload/origin check.
        if (deterministicName) firstFailure ??= error;
        continue;
      }
      if (nameParts.kind === "preparation" && payload?.version !== requestedVersion) continue;
      const isPreparation = nameParts.kind === "preparation";
      try {
        const payloadOriginRunId = normalizeRunId(isPreparation ? payload.originRunId : payload.producerRunId);
        const payloadOriginAttempt = normalizeRequiredRunAttempt(
          isPreparation ? payload.originRunAttempt : payload.producerRunAttempt,
          isPreparation ? "preparation evidence origin workflow run attempt" : "checkpoint producing run attempt",
          "artifact_provenance_mismatch",
        );
        if (payloadOriginRunId !== listedRunId) {
          fail("artifact_provenance_mismatch", isPreparation
            ? "Preparation evidence origin run does not match the producing run."
            : "Checkpoint producing run does not match its listing run.");
        }
        // The immutable payload is the only place where discovery can learn
        // which attempt produced the artifact. Re-authenticate that exact
        // attempt instead of trusting the latest run listing (which may be a
        // rerun with a different head, actor, or controller revision).
        const origin = await authenticatePreparationRun(api, auth, listedRun, {
          repository: targetRepository,
          repositoryId: targetRepositoryId,
          allowedActors,
          runAttempt: payloadOriginAttempt,
        });
        if (record.workflowRunId !== origin.runId || record.workflowRunHeadSha !== origin.headSha) {
          fail("artifact_provenance_mismatch", "Preparation artifact metadata does not match its authenticated producing attempt.");
        }
        if (record.workflowRunAttempt !== undefined && record.workflowRunAttempt !== origin.runAttempt) {
          fail("artifact_provenance_mismatch", "Preparation artifact workflow attempt does not match its authenticated producing attempt.");
        }
        if (isPreparation) {
          const evidence = assertPreparationArtifact(payload, {
            repository: targetRepository,
            trustedControllerSha: origin.headSha,
            originRunId: origin.runId,
            originRunAttempt: origin.runAttempt,
            version: requestedVersion,
            now,
          });
          assertPreparationAppIdentity(evidence, identity);
          if (nameParts.operationId !== evidence.operationId || nameParts.attempt !== evidence.attempt) {
            fail("artifact_identity_mismatch", "Preparation artifact name does not match its authenticated immutable payload.");
          }
          candidates.push({ evidence, artifact: record, origin });
        } else {
          // A checkpoint is only evidence when its own authenticated record
          // proves the producing run, attempt, controller revision and chain
          // link. The artifact name is a locator, never authority.
          const checkpoint = assertCheckpointRecord(payload, {
            repository: targetRepository,
            operationId: nameParts.operationId,
            attempt: nameParts.attempt,
            producerRunId: origin.runId,
            producerRunAttempt: origin.runAttempt,
            producerControllerSha: origin.headSha,
            now,
          });
          if (checkpoint.checkpointKind !== nameParts.kind) {
            fail("artifact_identity_mismatch", "Checkpoint artifact name does not match its authenticated record kind.");
          }
          checkpoints.push({ checkpoint, artifact: record, origin });
        }
      } catch (error) {
        firstFailure ??= error;
      }
    }
  }

  return { requestedVersion, targetRepository, identity, targetRepositoryId, candidates, checkpoints, firstFailure };
}

/** Group validated checkpoint records by kind for one candidate attempt. */
function selectAttemptCheckpoints(checkpoints, attempt) {
  const byKind = new Map();
  for (const entry of checkpoints) {
    if (entry.checkpoint.attempt !== Number(attempt)) continue;
    const kind = entry.checkpoint.checkpointKind;
    if (byKind.has(kind)) {
      fail("checkpoint_ambiguous", "Multiple immutable checkpoints claim the same kind and attempt.", {
        checkpointKind: kind,
        attempt: Number(attempt),
        artifacts: [byKind.get(kind).artifact.id, entry.artifact.id].sort((left, right) => left - right),
      });
    }
    byKind.set(kind, entry);
  }
  return byKind;
}

/**
 * Discover and validate the immutable checkpoint chain for this version from
 * trusted workflow history. Every record is authenticated against its
 * producing workflow run, attempt, actor, controller revision, artifact ID and
 * digest before it can influence a mutation; unrelated or forged artifacts are
 * rejected rather than trusted from their name.
 */
export async function discoverCheckpointChain(options = {}) {
  const { requestedVersion, targetRepository, checkpoints, firstFailure } = await collectPreparationCandidates(options);
  if (checkpoints.length === 0) {
    if (firstFailure) throw firstFailure;
    return { records: [], version: requestedVersion, repository: targetRepository };
  }
  const operationIds = new Set(checkpoints.map(({ checkpoint }) => checkpoint.operationId));
  for (const entry of checkpoints) {
    selectAttemptCheckpoints(checkpoints, entry.checkpoint.attempt);
  }
  if (operationIds.size > 1) {
    fail("duplicate_release_state", "Multiple authenticated release operations claim checkpoint records for this version.", {
      repository: targetRepository,
      version: requestedVersion,
      operations: [...operationIds].sort(),
    });
  }
  return {
    records: [...checkpoints].sort((left, right) => left.checkpoint.attempt - right.checkpoint.attempt),
    version: requestedVersion,
    repository: targetRepository,
  };
}

/**
 * Discover the single authenticated preparation artifact for a blocked
 * recovery path. Multiple attempts of one operation require checkpoint
 * authority, so this strict form still refuses to choose between them.
 */
export async function discoverPreparationEvidence(options = {}) {
  const { api, auth } = options;
  const { requestedVersion, targetRepository, candidates, firstFailure } = await collectPreparationCandidates(options);
  if (candidates.length === 0) {
    await assertNoConflictingVersionState(api, auth, requestedVersion, { repository: targetRepository });
    if (firstFailure) throw firstFailure;
    return undefined;
  }
  const operationIds = new Set(candidates.map(({ evidence: item }) => item.operationId));
  if (operationIds.size > 1) {
    fail("duplicate_release_state", "Multiple authenticated release operations claim the requested version.", {
      repository: targetRepository,
      version: requestedVersion,
      operations: [...operationIds].sort(),
    });
  }
  if (candidates.length > 1) {
    // Selecting a later preparation attempt requires checkpoint-chain
    // authority. That chain is a separate recovery unit, so discovery must
    // preserve ambiguity and block rather than silently choosing one.
    fail("duplicate_release_state", "Multiple authenticated preparation artifacts claim the requested operation; checkpoint authority is required to choose an attempt.", {
      operationId: candidates[0].evidence.operationId,
      attempts: [...new Set(candidates.map(({ evidence: item }) => item.attempt))].sort((left, right) => left - right),
      artifacts: candidates.map(({ artifact }) => artifact.id).sort((left, right) => left - right),
    });
  }
  const selected = candidates[0];
  return {
    state: { ...selected.evidence, artifact: selected.artifact },
    evidence: selected.evidence,
    artifact: selected.artifact,
    origin: selected.origin,
  };
}

/**
 * Resolve what a repeated production request means for one repository/version
 * operation:
 *
 *   fresh       - no authenticated preparation exists; prepare attempt 1
 *   resume      - an attempt whose recorded base is current main, or a
 *                 candidate that already merged and must reach publication
 *   replacement - every recorded attempt is stale; the next bounded attempt is
 *                 prepared from current main with re-captured release notes
 *
 * The attempt count is derived from the immutable preparation artifacts, so it
 * survives reruns. A stale attempt that still has an open pull request is
 * dispositioned and closed before the replacement is prepared, and a candidate
 * with manual edits stops instead of being closed or overwritten.
 */
async function resolveReleaseRequest({
  api,
  auth,
  artifacts,
  context,
  version,
  repository,
  repositoryId,
  allowedActors = [],
  now = Date.now(),
  botLogin,
  producer,
} = {}) {
  const { requestedVersion, targetRepository, identity, candidates, firstFailure } = await collectPreparationCandidates({
    api,
    auth,
    artifacts,
    context,
    version,
    repository,
    repositoryId,
    allowedActors,
    now,
  });
  if (candidates.length === 0) {
    await assertNoConflictingVersionState(api, auth, requestedVersion, { repository: targetRepository });
    if (firstFailure) throw firstFailure;
    return { kind: "fresh", attempt: 1 };
  }
  const operationIds = new Set(candidates.map(({ evidence }) => evidence.operationId));
  if (operationIds.size > 1) {
    fail("duplicate_release_state", "Multiple authenticated release operations claim the requested version.", {
      repository: targetRepository,
      version: requestedVersion,
      operations: [...operationIds].sort(),
    });
  }
  const operationId = candidates[0].evidence.operationId;
  const mainRef = await apiCall(api, auth, "getRef", ["heads/main"]);
  const currentMainSha = normalizeSha(mainRef.object?.sha, "current main SHA");
  const ordered = [...candidates].sort((left, right) => left.evidence.attempt - right.evidence.attempt);
  const attempts = ordered.map(({ evidence }) => evidence.attempt);
  const current = ordered.filter(({ evidence }) => evidence.baseSha === currentMainSha);
  if (current.length > 1) {
    fail("duplicate_release_state", "Multiple authenticated preparation attempts claim current main.", {
      repository: targetRepository,
      version: requestedVersion,
      operationId,
      attempts: current.map(({ evidence }) => evidence.attempt),
    });
  }
  if (current.length === 1) {
    return { kind: "resume", state: { ...current[0].evidence, artifact: current[0].artifact } };
  }
  const highest = ordered.at(-1);
  const branch = branchName(highest.evidence.operationId, highest.evidence.version, highest.evidence.attempt);
  // The immutable chain is the durable authority for this attempt's pull
  // request association; a live branch lookup is only the fallback when no
  // checkpoint recorded one.
  const chain = await discoverCheckpointChain({
    api,
    auth,
    artifacts,
    context,
    version: requestedVersion,
    repository: targetRepository,
    repositoryId: identity.repositoryId,
    allowedActors,
    now,
  });
  const recorded = selectAttemptCheckpoints(chain.records, highest.evidence.attempt);
  const recordedPr = recorded.get("merged") ?? recorded.get("pr-created");
  const recordedStale = recorded.get("stale-base");
  const live = recordedPr === undefined
    ? await readReleasePullRequestByBranch(api, auth, branch)
    : asObject(await apiCall(api, auth, "getPullRequest", [recordedPr.checkpoint.prNumber]), "release pull request");
  if (live !== undefined) {
    const runtime = {
      prNumber: live.number,
      prHeadSha: highest.evidence.preparedCommitSha,
      prBaseSha: highest.evidence.baseSha,
    };
    // The live candidate must still be this attempt's own unaltered App pull
    // request. Manual edits stop the operation instead of being closed,
    // overwritten or force-pushed.
    assertPullRequestIdentity(live, {
      repositoryId: identity.repositoryId,
      branch,
      headSha: highest.evidence.preparedCommitSha,
      baseSha: highest.evidence.baseSha,
      botLogin,
      allowStaleBase: true,
    });
    if (live.merged === true || live.merged_at) {
      return {
        kind: "resume",
        state: { ...highest.evidence, artifact: highest.artifact },
        runtime: { ...runtime, mergedSha: normalizeSha(live.merge_commit_sha, "recorded merged SHA") },
      };
    }
    if (recorded.get("merged") !== undefined) {
      fail("mutation_ambiguous", "A merged checkpoint exists but the live release pull request is not merged.", {
        prNumber: live.number,
        attempt: highest.evidence.attempt,
      });
    }
    if (live.state !== "open" && recordedStale === undefined && recordedPr !== undefined) {
      // A recorded association that is already closed without a terminal
      // disposition is ambiguous: the close and the disposition are not atomic.
      fail("mutation_ambiguous", "A recorded release pull request is closed without a durable stale-attempt disposition.", {
        prNumber: live.number,
        attempt: highest.evidence.attempt,
      });
    }
    if (live.state === "open") {
      await persistStaleDisposition({
        artifacts,
        evidence: highest.evidence,
        artifact: highest.artifact,
        prNumber: live.number,
        currentMainSha,
        producer,
        recorded: recordedStale,
      });
      await mutationWithReconcile(
        api,
        auth,
        () => invoke(api, "updatePullRequest", [live.number, { state: "closed" }]),
        async () => {
          const observed = await apiCall(api, auth, "getPullRequest", [live.number]);
          return observed.state === "closed" ? { completed: true, value: observed } : { ambiguous: true };
        },
      );
    }
  }
  if (highest.evidence.attempt >= MAX_CANDIDATE_ATTEMPTS) {
    fail("base_changed_repeatedly", "Candidate attempt budget is exhausted after repeated base changes.", {
      repository: targetRepository,
      version: requestedVersion,
      operationId,
      attempts,
      bound: MAX_CANDIDATE_ATTEMPTS,
      currentMainSha,
    });
  }
  return { kind: "replacement", attempt: highest.evidence.attempt + 1, operationId, previousAttempt: highest.evidence.attempt };
}

/**
 * Reconcile the immutable checkpoint chain with live GitHub state before any
 * mutation. A recorded merge is adopted only when the live pull request is
 * merged; a recorded PR association is adopted for this attempt; a terminal
 * disposition or a contradiction stops instead of guessing.
 */
async function reconcileRecordedCheckpoints({ api, auth, chain, state, botLogin }) {
  if (!chain || chain.records.length === 0) return { kind: "none" };
  const recorded = selectAttemptCheckpoints(chain.records, state.attempt);
  const branch = branchName(state.operationId, state.version, state.attempt);
  const identity = {
    repositoryId: state.repositoryId,
    branch,
    headSha: state.preparedCommitSha,
    baseSha: state.baseSha,
    botLogin,
    allowStaleBase: true,
  };
  const merged = recorded.get("merged");
  const prCreated = recorded.get("pr-created");
  const stale = recorded.get("stale-base");
  if (merged !== undefined) {
    const live = asObject(await apiCall(api, auth, "getPullRequest", [merged.checkpoint.prNumber]), "release pull request");
    assertPullRequestIdentity(live, identity);
    if (!(live.merged === true || live.merged_at)) {
      fail("mutation_ambiguous", "A merged checkpoint exists but the live release pull request is not merged.", {
        prNumber: merged.checkpoint.prNumber,
        artifact: merged.artifact.id,
      });
    }
    return {
      kind: "merged",
      prNumber: merged.checkpoint.prNumber,
      mergedSha: normalizeSha(live.merge_commit_sha ?? merged.checkpoint.mergedSha, "recorded merged SHA"),
    };
  }
  if (prCreated !== undefined) {
    const live = asObject(await apiCall(api, auth, "getPullRequest", [prCreated.checkpoint.prNumber]), "release pull request");
    assertPullRequestIdentity(live, identity);
    if (live.merged === true || live.merged_at) {
      return {
        kind: "merged",
        prNumber: prCreated.checkpoint.prNumber,
        mergedSha: normalizeSha(live.merge_commit_sha, "live merged SHA"),
      };
    }
    if (live.state !== "open") {
      fail("candidate_closed", "Recorded release pull request is closed before merge.", {
        prNumber: prCreated.checkpoint.prNumber,
      });
    }
    return { kind: "pr-created", prNumber: prCreated.checkpoint.prNumber };
  }
  if (stale !== undefined) {
    fail("checkpoint_ambiguous", "A terminal stale-attempt disposition contradicts the active candidate state.", {
      attempt: state.attempt,
      artifact: stale.artifact.id,
      currentMainSha: stale.checkpoint.currentMainSha,
    });
  }
  return { kind: "none" };
}

function pullRequestAssociationMatches(run, { headSha, baseSha, repository, repositoryId } = {}) {
  if (!Array.isArray(run.pull_requests) || run.pull_requests.length === 0) {
    fail("untrusted_workflow", "Pull-request workflow run is missing its pull request association.");
  }
  const expectedRepository = repository ? normalizeRepository(repository).toLowerCase() : undefined;
  const expectedRepositoryId = repositoryId === undefined ? undefined : normalizePositiveInteger(repositoryId, "repository ID");
  if (expectedRepository === undefined && expectedRepositoryId === undefined) {
    fail("untrusted_workflow", "Pull-request workflow run has no trusted repository identity.");
  }
  return run.pull_requests.some((pullRequest) => {
    const value = asObject(pullRequest, "workflow pull request association");
    const head = asObject(value.head, "workflow pull request head");
    const base = asObject(value.base, "workflow pull request base");
    const headRepository = asObject(head.repo, "workflow pull request head repository");
    const baseRepository = asObject(base.repo, "workflow pull request base repository");
    const headRepositoryId = headRepository.id ?? headRepository.repository_id;
    const baseRepositoryId = baseRepository.id ?? baseRepository.repository_id;
    const expectedRepositoryName = expectedRepository?.split("/").at(-1);
    const repositoryNameMatches = (repositoryValue) => {
      if (expectedRepositoryId === undefined && repositoryValue.full_name === undefined && repositoryValue.name === undefined) return false;
      if (repositoryValue.full_name !== undefined && String(repositoryValue.full_name).toLowerCase() !== expectedRepository) return false;
      if (repositoryValue.name !== undefined && String(repositoryValue.name).toLowerCase() !== expectedRepositoryName) return false;
      return true;
    };
    const repositoryIdsMatch = expectedRepositoryId === undefined
      ? true
      : Number(headRepositoryId) === expectedRepositoryId && Number(baseRepositoryId) === expectedRepositoryId;
    const repositoryNamesMatch = expectedRepository === undefined
      ? true
      : repositoryNameMatches(headRepository) && repositoryNameMatches(baseRepository);
    return String(head.sha ?? "").toLowerCase() === normalizeSha(headSha, "pull request head SHA") &&
      String(base.sha ?? "").toLowerCase() === normalizeSha(baseSha, "pull request base SHA") &&
      base.ref === "main" &&
      repositoryIdsMatch && repositoryNamesMatch;
  });
}

function workflowRunState(run) {
  const status = String(run.status ?? "").toLowerCase();
  if (!["queued", "in_progress", "completed", "waiting", "requested", "pending"].includes(status)) {
    fail("malformed_response", "Workflow run status is malformed.");
  }
  if (status !== "completed") return "pending";
  const conclusion = String(run.conclusion ?? "").toLowerCase();
  if (!conclusion) fail("malformed_response", "Completed workflow run has no conclusion.");
  return conclusion === "success" ? "success" : "failed";
}

function jobState(job, label = "workflow job") {
  const value = asObject(job, label);
  const status = String(value.status ?? "").toLowerCase();
  if (!["queued", "in_progress", "completed", "waiting", "requested", "pending"].includes(status)) {
    fail("malformed_response", `${label} status is malformed.`);
  }
  if (status !== "completed") return "pending";
  const conclusion = String(value.conclusion ?? "").toLowerCase();
  if (!conclusion) fail("malformed_response", `Completed ${label} has no conclusion.`);
  return conclusion === "success" ? "success" : "failed";
}

function selectWorkflowRun(workflowRuns, {
  headSha,
  baseSha,
  repository,
  repositoryId,
  event,
  workflowPath,
  requireMainBranch = false,
  runAttempt,
} = {}) {
  const normalizedHead = normalizeSha(headSha, "candidate head SHA");
  const candidates = [];
  for (const run of workflowRuns) {
    const value = asObject(run, "workflow run");
    if (String(value.head_sha ?? "").toLowerCase() !== normalizedHead) continue;
    const identity = assertWorkflowRunIdentity(value, {
      headSha: normalizedHead,
      repository,
      repositoryId,
      event,
      workflowPath,
      requireMainBranch,
    });
    if (event === "pull_request" && !pullRequestAssociationMatches(value, { headSha: normalizedHead, baseSha, repository, repositoryId })) continue;
    if (runAttempt !== undefined && identity.runAttempt !== normalizeRunAttempt(runAttempt)) continue;
    candidates.push(identity);
  }
  // Attempts are ordered only within one workflow run. A retry of an older
  // run must never outrank a newer run for the same SHA merely because its
  // attempt number is larger.
  candidates.sort((left, right) => {
    if (left.runId === right.runId) return right.runAttempt - left.runAttempt;
    const leftTime = Date.parse(left.value.created_at ?? left.value.updated_at ?? "");
    const rightTime = Date.parse(right.value.created_at ?? right.value.updated_at ?? "");
    if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return rightTime - leftTime;
    return right.runId - left.runId;
  });
  return candidates[0];
}

function checkRunForContext(checkRuns, context, headSha) {
  const normalizedHead = normalizeSha(headSha, "candidate head SHA");
  const matches = checkRuns.filter((run) => {
    const value = asObject(run, "check run");
    return normalizedCheckName(value.name) === normalizedCheckName(context) &&
      String(value.head_sha ?? "").toLowerCase() === normalizedHead;
  });
  if (matches.length > 1) fail("untrusted_workflow", `Multiple current check runs report ${context}.`);
  return matches[0];
}

function assertCheckRunIdentity(checkRun, context) {
  const value = asObject(checkRun, "check run");
  if (typeof value.url !== "string" || value.url.length === 0) fail("untrusted_workflow", `Check run ${context} has no canonical URL.`);
  if (Number(value.app?.id) !== GITHUB_ACTIONS_APP_ID) fail("untrusted_workflow", `Check run ${context} is not owned by GitHub Actions.`);
  return value;
}

function assertJobIdentity(job, run, headSha, context) {
  const value = asObject(job, "workflow job");
  // The attempt is authenticated by the /attempts/{attempt}/jobs endpoint;
  // GitHub's workflow-job DTO commonly omits run_attempt. If a provider does
  // include the optional field, it must agree with that authenticated URL.
  if (Number(value.run_id) !== run.runId || String(value.head_sha ?? "").toLowerCase() !== normalizeSha(headSha, "workflow job head SHA")) {
    fail("untrusted_workflow", `Workflow job ${context} is not tied to the selected run attempt and head.`);
  }
  if (value.run_attempt !== undefined && normalizeRunAttempt(value.run_attempt) !== run.runAttempt) {
    fail("untrusted_workflow", `Workflow job ${context} is not tied to the selected run attempt and head.`);
  }
  if (typeof value.check_run_url !== "string" || value.check_run_url.length === 0) {
    fail("untrusted_workflow", `Workflow job ${context} has no check-run URL.`);
  }
  return value;
}

function jobsForContext(jobs, context, run, headSha) {
  const named = jobs.filter((job) => checkContextMatches(job?.name, context));
  const current = [];
  for (const job of named) {
    const value = asObject(job, "workflow job");
    if (value.run_id === undefined || value.head_sha === undefined) {
      fail("malformed_response", `Workflow job ${context} is missing run identity.`);
    }
    const attemptMatches = value.run_attempt === undefined || normalizeRunAttempt(value.run_attempt) === run.runAttempt;
    if (Number(value.run_id) === run.runId && String(value.head_sha).toLowerCase() === normalizeSha(headSha, "workflow job head SHA") && attemptMatches) current.push(value);
  }
  if (current.length > 1) fail("untrusted_workflow", `Multiple current workflow jobs report ${context}.`);
  return { named, current: current[0] };
}

function jobsForWorkflowRun(jobs, run, headSha, { includeEdge = false } = {}) {
  const statuses = {};
  const failures = [];
  let edge;
  for (const context of REQUIRED_CHECK_CONTEXTS) {
    const { named, current } = jobsForContext(jobs, context, run, headSha);
    if (!current) {
      statuses[context] = named.length > 0 ? "stale" : "missing";
      continue;
    }
    const job = asObject(current, "workflow job");
    const state = jobState(job, `workflow job ${context}`);
    if (state === "failed") {
      statuses[context] = String(job.conclusion).toLowerCase();
      failures.push({ context, reason: statuses[context] });
    } else {
      statuses[context] = state;
    }
  }
  if (includeEdge) {
    const edgeJobs = jobs.filter((job) => normalizedCheckName(job?.name) === "publish-edge");
    const currentEdges = [];
    for (const job of edgeJobs) {
      const value = asObject(job, "publish-edge workflow job");
      if (value.run_id === undefined || value.head_sha === undefined) {
        fail("malformed_response", "publish-edge workflow job is missing run identity.");
      }
      const attemptMatches = value.run_attempt === undefined || normalizeRunAttempt(value.run_attempt) === run.runAttempt;
      if (Number(value.run_id) === run.runId && String(value.head_sha).toLowerCase() === normalizeSha(headSha, "publish-edge head SHA") && attemptMatches) currentEdges.push(value);
    }
    if (currentEdges.length > 1) fail("untrusted_workflow", "Multiple current publish-edge jobs were returned.");
    edge = currentEdges[0];
    if (!edge) {
      statuses["publish-edge"] = edgeJobs.length > 0 ? "stale" : "missing";
    } else {
      const edgeState = jobState(edge, "publish-edge workflow job");
      statuses["publish-edge"] = edgeState === "failed" ? String(edge.conclusion).toLowerCase() : edgeState;
      if (edgeState === "failed") failures.push({ context: "publish-edge", reason: statuses["publish-edge"] });
    }
  }
  const pending = Object.values(statuses).some((value) => ["pending", "missing", "stale"].includes(value));
  return { statuses, failures, pending, edge };
}

/**
 * The release gate always covers exactly the seven approved verification
 * contexts. A narrower, duplicated or extended set would be a silent policy
 * bypass, so it is refused instead of being evaluated.
 */
function canonicalCheckContexts(requiredContexts) {
  const values = asArray(requiredContexts, "required check contexts");
  for (const context of values) {
    if (typeof context !== "string" || context.trim() === "") {
      fail("check_contexts_invalid", "Required check contexts must be non-empty strings.");
    }
  }
  const normalized = values.map(normalizedCheckName);
  const canonical = REQUIRED_CHECK_CONTEXTS.map(normalizedCheckName);
  if (
    normalized.length !== canonical.length ||
    new Set(normalized).size !== normalized.length ||
    canonical.some((context) => !normalized.includes(context))
  ) {
    fail("check_contexts_invalid", "Release gates must cover exactly the seven approved verification contexts.", {
      contexts: values,
    });
  }
  return values;
}

export function evaluateRequiredChecks(checkRuns, {
  headSha,
  baseSha,
  workflowRuns = [],
  workflowJobs,
  requiredContexts = REQUIRED_CHECK_CONTEXTS,
  repository,
  repositoryId,
  runAttempt,
} = {}) {
  const head = normalizeSha(headSha, "candidate head SHA");
  const base = normalizeSha(baseSha, "candidate base SHA");
  const contexts = canonicalCheckContexts(requiredContexts);
  const runs = collectionItems(checkRuns, "check_runs", "check runs");
  const workflows = collectionItems(workflowRuns, "workflow_runs", "workflow runs");
  const jobs = workflowJobs === undefined ? undefined : collectionItems(workflowJobs, "jobs", "workflow run jobs");
  const failures = [];
  const statuses = {};
  const run = selectWorkflowRun(workflows, {
    headSha: head,
    baseSha: base,
    repository,
    repositoryId,
    event: "pull_request",
    workflowPath: CI_WORKFLOW_PATH,
    runAttempt,
  });
  if (!run) {
    for (const context of contexts) statuses[context] = "missing";
    return { state: "pending", statuses, failures, headSha: head, baseSha: base };
  }
  const runResult = workflowRunState(run.value);
  if (runResult === "failed") {
    for (const context of contexts) {
      statuses[context] = "failed";
      failures.push({ context, reason: "workflow_failed" });
    }
    return { state: "failed", statuses, failures, headSha: head, baseSha: base, workflowRunId: run.runId, workflowRunAttempt: run.runAttempt };
  }
  if (jobs === undefined) {
    for (const context of contexts) statuses[context] = "pending";
    return { state: "pending", statuses, failures, headSha: head, baseSha: base, workflowRunId: run.runId, workflowRunAttempt: run.runAttempt };
  }
  for (const context of contexts) {
    const current = checkRunForContext(runs, context, head);
    if (!current) {
      statuses[context] = "missing";
      continue;
    }
    const check = assertCheckRunIdentity(current, context);
    const { named, current: currentJob } = jobsForContext(jobs, context, run, head);
    if (!currentJob) {
      statuses[context] = named.length > 0 ? "stale" : "missing";
      continue;
    }
    const job = assertJobIdentity(currentJob, run, head, context);
    if (job.check_run_url !== check.url) fail("untrusted_workflow", `Workflow job ${context} is not tied to its check run.`);
    const checkResult = jobState(check, `check run ${context}`);
    const jobResult = jobState(job, `workflow job ${context}`);
    if (checkResult === "failed" || jobResult === "failed") {
      const conclusion = String(check.conclusion ?? job.conclusion ?? "failed").toLowerCase();
      statuses[context] = conclusion;
      failures.push({ context, reason: conclusion });
    } else if (checkResult === "pending" || jobResult === "pending") {
      statuses[context] = "pending";
    } else {
      statuses[context] = "success";
    }
  }
  const pending = Object.values(statuses).some((value) => ["pending", "missing", "stale"].includes(value));
  if (failures.length > 0) return { state: "failed", statuses, failures, workflowRunId: run.runId, workflowRunAttempt: run.runAttempt };
  if (pending || Object.keys(statuses).length !== contexts.length || runResult === "pending") return { state: "pending", statuses, failures, headSha: head, baseSha: base, workflowRunId: run.runId, workflowRunAttempt: run.runAttempt };
  return { state: "passed", statuses, failures: [], headSha: head, baseSha: base, workflowRunId: run.runId, workflowRunAttempt: run.runAttempt };
}

export async function waitForPullRequestChecks(api, auth, options = {}) {
  const clock = normalizeClock(options.clock);
  return pollUntil(
    async () => {
      const checks = await apiCall(api, auth, "getCheckRuns", [options.headSha]);
      const workflows = await apiCall(api, auth, "getWorkflowRuns", [{
        headSha: options.headSha,
        event: "pull_request",
        workflow: CI_WORKFLOW_PATH,
      }]);
      const workflowRuns = collectionItems(workflows, "workflow_runs", "workflow runs");
      let workflowJobs;
      const selected = selectWorkflowRun(workflowRuns, {
        headSha: options.headSha,
        baseSha: options.baseSha,
        repository: options.repository,
        repositoryId: options.repositoryId,
        event: "pull_request",
        workflowPath: CI_WORKFLOW_PATH,
        runAttempt: options.runAttempt,
      });
      if (selected) workflowJobs = await apiCall(api, auth, "getWorkflowRunJobs", [selected.runId, selected.runAttempt]);
      return evaluateRequiredChecks(checks, {
        ...options,
        repository: options.repository,
        repositoryId: options.repositoryId,
        workflowRuns,
        workflowJobs,
      });
    },
    { ...options, clock, label: options.label ?? "pull request verification" },
  );
}

function protectionObject(value, label) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    fail("protection_malformed", `${label} must be an object in the branch protection response.`);
  }
  return value;
}

function protectionArray(value, label) {
  if (!Array.isArray(value)) fail("protection_malformed", `${label} must be an array in the branch protection response.`);
  return value;
}

function protectionBoolean(value, label, expected) {
  if (typeof value !== "boolean") fail("protection_malformed", `${label} must be a boolean in the branch protection response.`);
  if (value !== expected) fail("protection_changed", `${label} does not match the approved branch protection baseline.`);
}

function protectionContexts(contexts, expectedContexts, label) {
  const values = protectionArray(contexts, label);
  const expected = expectedContexts.map(normalizedCheckName);
  const normalized = values.map((context) => {
    if (typeof context !== "string" || context.trim() === "") {
      fail("protection_malformed", `${label} contains an invalid check context.`);
    }
    return normalizedCheckName(context);
  });
  if (normalized.length !== expected.length || new Set(normalized).size !== normalized.length || expected.some((context) => !normalized.includes(context))) {
    fail("protection_changed", "Main branch required status-check contexts differ from the approved baseline.");
  }
}

function assertEmptyAllowances(allowances, label) {
  const value = protectionObject(allowances, label);
  for (const key of ["users", "teams", "apps"]) {
    const values = protectionArray(value[key], `${label}.${key}`);
    if (values.length !== 0) fail("protection_changed", `${label} contains a branch protection bypass allowance.`);
  }
}

function assertPersonalOwnerEvidence(repositoryEvidence, expectedRepositoryId) {
  const repository = asObject(repositoryEvidence, "authenticated repository metadata");
  const actualId = normalizePositiveInteger(repository.id, "authenticated repository ID");
  const expectedId = normalizePositiveInteger(expectedRepositoryId, "expected repository ID");
  if (actualId !== expectedId) fail("repository_scope_mismatch", "Authenticated repository identity does not match the release target.");
  const owner = asObject(repository.owner, "authenticated repository owner");
  if (owner.type !== "User") {
    fail("protection_malformed", "An omitted bypass allowance is safe only for an authenticated personal repository.");
  }
}

/**
 * Validate the response from GET /repos/{owner}/{repo}/branches/main/protection.
 *
 * The REST representation wraps the relevant booleans in `{ enabled }` objects
 * and exposes each required check as `{ context, app_id }`. Treat absent or
 * malformed fields as unsafe evidence so the caller cannot fall back to a
 * screenshot, an optional flag, or a weaker merge path.
 */
export function assertApprovedBranchProtection(protection, expectedContexts = REQUIRED_CHECK_CONTEXTS, repositoryEvidence) {
  const value = protectionObject(protection, "branch protection");
  const contexts = protectionArray(expectedContexts, "expected required contexts").map((context) => {
    if (typeof context !== "string" || context.trim() === "") fail("protection_malformed", "Expected required contexts contain an invalid value.");
    return context;
  });
  const canonicalContexts = REQUIRED_CHECK_CONTEXTS.map(normalizedCheckName);
  const normalizedContexts = contexts.map(normalizedCheckName);
  if (
    normalizedContexts.length !== canonicalContexts.length ||
    new Set(normalizedContexts).size !== normalizedContexts.length ||
    canonicalContexts.some((context) => !normalizedContexts.includes(context))
  ) {
    fail("protection_malformed", "Expected required contexts must match all seven protected verification contexts.");
  }

  const checks = protectionObject(value.required_status_checks, "required_status_checks");
  protectionBoolean(checks.strict, "required_status_checks.strict", true);
  const requiredChecks = protectionArray(checks.checks, "required_status_checks.checks");
  if (requiredChecks.length !== contexts.length) {
    fail("protection_changed", "Main branch required status checks differ from the approved baseline.");
  }
  const checkContexts = [];
  for (const entry of requiredChecks) {
    const check = protectionObject(entry, "required_status_checks.checks entry");
    if (typeof check.context !== "string" || check.context.trim() === "") {
      fail("protection_malformed", "Required status-check context is malformed.");
    }
    if (!Number.isSafeInteger(check.app_id)) {
      fail("protection_malformed", "Required status-check app_id is malformed.");
    }
    if (check.app_id !== GITHUB_ACTIONS_APP_ID) {
      fail("protection_changed", "Required status checks are not bound to GitHub Actions.");
    }
    checkContexts.push(check.context);
  }
  protectionContexts(checkContexts, contexts, "required_status_checks.checks");
  // GitHub currently returns both `contexts` and the richer `checks` array.
  // When the legacy field is present, require it to describe the same exact
  // set so an inconsistent response cannot pass through the richer field.
  if (Object.prototype.hasOwnProperty.call(checks, "contexts")) {
    protectionContexts(checks.contexts, contexts, "required_status_checks.contexts");
  }

  const reviews = protectionObject(value.required_pull_request_reviews, "required_pull_request_reviews");
  if (!Number.isSafeInteger(reviews.required_approving_review_count)) {
    fail("protection_malformed", "required_pull_request_reviews.required_approving_review_count is malformed.");
  }
  if (reviews.required_approving_review_count !== 0) {
    fail("protection_changed", "Main branch unexpectedly requires approving reviews.");
  }
  protectionBoolean(reviews.require_code_owner_reviews, "required_pull_request_reviews.require_code_owner_reviews", false);
  protectionBoolean(reviews.require_last_push_approval, "required_pull_request_reviews.require_last_push_approval", false);
  if (Object.prototype.hasOwnProperty.call(reviews, "bypass_pull_request_allowances")) {
    assertEmptyAllowances(reviews.bypass_pull_request_allowances, "required_pull_request_reviews.bypass_pull_request_allowances");
  } else {
    assertPersonalOwnerEvidence(repositoryEvidence?.repository, repositoryEvidence?.expectedRepositoryId);
  }

  for (const [key, expected] of [
    ["enforce_admins", true],
    ["required_linear_history", true],
    ["required_conversation_resolution", true],
    ["allow_force_pushes", false],
    ["allow_deletions", false],
  ]) {
    const setting = protectionObject(value[key], key);
    protectionBoolean(setting.enabled, `${key}.enabled`, expected);
  }
  return true;
}

async function validateMainBranchProtection(api, auth, expectedContexts = REQUIRED_CHECK_CONTEXTS, { repository, repositoryId } = {}) {
  if (typeof api?.getBranchProtection !== "function" || typeof api?.getRepository !== "function") {
    fail("protection_evidence_unavailable", "Main branch protection evidence is unavailable.");
  }
  if (repositoryId === undefined) fail("repository_scope_mismatch", "Expected repository identity is required for protection validation.");
  const repositoryInfo = asObject(await apiCall(api, auth, "getRepository", []), "authenticated repository metadata");
  const actualRepositoryId = normalizePositiveInteger(repositoryInfo.id, "authenticated repository ID");
  const expectedRepositoryId = normalizePositiveInteger(repositoryId, "expected repository ID");
  if (actualRepositoryId !== expectedRepositoryId) fail("repository_scope_mismatch", "Authenticated repository identity does not match the release target.");
  if (repository && String(repositoryInfo.full_name ?? "").toLowerCase() !== normalizeRepository(repository).toLowerCase()) {
    fail("repository_scope_mismatch", "Authenticated repository name does not match the release target.");
  }
  const protection = await apiCall(api, auth, "getBranchProtection", ["main"]);
  assertApprovedBranchProtection(protection, expectedContexts, {
    repository: repositoryInfo,
    expectedRepositoryId,
  });
  return protection;
}

async function validatePullRequestGates(api, auth, state, options = {}) {
  const pr = await apiCall(api, auth, "getPullRequest", [state.prNumber]);
  asObject(pr, "pull request");
  const expectedBranch = branchName(state.operationId, state.version, state.attempt);
  if (state.branch !== undefined && state.branch !== expectedBranch) {
    fail("candidate_identity_mismatch", "Recorded release branch does not match the generated candidate identity.");
  }
  const { merged } = assertPullRequestIdentity(pr, {
    repositoryId: state.repositoryId,
    branch: expectedBranch,
    headSha: state.preparedCommitSha,
    baseSha: state.baseSha,
    botLogin: options.botLogin,
  });
  if (merged) return { state: "merged", pr };
  if (pr.state !== "open") fail("candidate_closed", "Release PR is closed before merge.");
  if (typeof api.listReviewThreads !== "function") fail("review_threads_unavailable", "Release PR discussion evidence is unavailable.");
  const threads = await apiCall(api, auth, "listReviewThreads", [state.prNumber]);
  if (asArray(threads, "review threads").some((thread) => thread.isResolved === false || thread.resolved === false)) {
    fail("unresolved_discussion", "Release PR has unresolved discussions.");
  }
  if (typeof api.listReviewRequests !== "function") fail("review_requests_unavailable", "Release PR reviewer-request evidence is unavailable.");
  const requests = await apiCall(api, auth, "listReviewRequests", [state.prNumber]);
  const requested = asObject(requests, "review requests");
  if ((requested.users?.length ?? 0) > 0 || (requested.teams?.length ?? 0) > 0) fail("review_requested", "Release PR has an unhandled review request.");
  if (typeof api.listReviews !== "function") fail("reviews_unavailable", "Release PR review evidence is unavailable.");
  const reviews = await apiCall(api, auth, "listReviews", [state.prNumber]);
  if (asArray(reviews, "reviews").some((review) => String(review.state).toUpperCase() === "CHANGES_REQUESTED")) {
    fail("changes_requested", "Release PR has a changes-requested review.");
  }
  return { state: "open", pr, baseSha: state.baseSha };
}

function branchName(operationId, version, attempt) {
  const parsed = parseStableVersion(version);
  return `${operationId}-v${parsed.text}-attempt-${attempt}`;
}

function releaseTag(version) {
  return `v${parseStableVersion(version).text}`;
}

function minorTag(version) {
  const parsed = parseStableVersion(version);
  return `${parsed.majorText}.${parsed.minorText}`;
}

function operationIdFor({ repository, version, originRunId }) {
  return `release-${sha256(`${repository}\0${version}\0${originRunId}`).slice(0, 20)}`;
}

async function createCandidateCommit(api, auth, evidence) {
  const files = normalizeCandidateFiles(evidence.candidateFiles);
  const baseCommit = await apiCall(api, auth, "getCommit", [evidence.baseSha]);
  const baseTreeSha = normalizeSha(baseCommit.tree?.sha ?? baseCommit.treeSha, "base tree SHA");
  const treeEntries = [];
  for (const file of files) {
    const blob = await mutationWithReconcile(
      api,
      auth,
      () => api.createBlob ? api.createBlob(file.content) : invoke(api, "createBlob", [file.content]),
      async () => ({ completed: false, ambiguous: true }),
    );
    treeEntries.push({ path: file.path, mode: file.mode, type: "blob", sha: normalizeSha(blob.sha, "candidate blob SHA") });
  }
  const tree = await mutationWithReconcile(
    api,
    auth,
    () => invoke(api, "createTree", [{ base_tree: baseTreeSha, tree: treeEntries }]),
    async () => ({ completed: false, ambiguous: true }),
  );
  const treeSha = normalizeSha(tree.sha, "candidate tree SHA");
  const commit = await mutationWithReconcile(
    api,
    auth,
    () => invoke(api, "createCommit", [{ message: `chore(release): prepare ${releaseTag(evidence.version)}`, tree: treeSha, parents: [evidence.baseSha] }]),
    async () => ({ completed: false, ambiguous: true }),
  );
  const commitSha = normalizeSha(commit.sha, "prepared commit SHA");
  return { commitSha, treeSha };
}

async function computeTreeDigestFromEntries(api, entries) {
  const digest = crypto.createHash("sha256");
  for (const entry of entries.sort((left, right) => compareSafePaths(String(left.path), String(right.path)))) {
    const filePath = boundedString(entry.path, "tree path", 300);
    if (!SAFE_PATH_PATTERN.test(filePath) || !/^(100644|100755|120000)$/.test(String(entry.mode))) fail("tree_digest_unavailable", "Tree contains an unsafe entry.");
    const blob = await invoke(api, "getBlob", [entry.sha]);
    if (blob.encoding !== "base64" || typeof blob.content !== "string") fail("tree_digest_unavailable", "Tree blob content is not base64 encoded.");
    const content = Buffer.from(blob.content.replace(/\n/g, ""), "base64");
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(content.length));
    digest.update(filePath).update("\0").update(String(entry.mode)).update("\0").update(length).update(content);
  }
  return digest.digest("hex");
}

async function verifyCandidateTree(api, auth, commitSha, expectedDigest, expectedTree, candidateFiles = []) {
  const commit = await apiCall(api, auth, "getCommit", [commitSha]);
  const treeSha = normalizeSha(commit.tree?.sha ?? commit.treeSha, "candidate tree SHA");
  if (typeof api.getTreeDigest === "function") {
    const digest = normalizeDigest(await apiCall(api, auth, "getTreeDigest", [treeSha]), "candidate tree digest");
    if (digest !== expectedDigest) fail("candidate_tree_mismatch", "Prepared commit tree does not match the immutable expected tree.");
    return { treeSha, expectedDigest };
  }
  if (typeof api.getTree !== "function" || typeof api.getBlob !== "function") fail("candidate_tree_verification_unavailable", "Exact candidate tree verification is unavailable.");
  const tree = await apiCall(api, auth, "getTree", [treeSha]);
  if (tree.truncated === true) fail("candidate_tree_verification_unavailable", "GitHub returned a truncated candidate tree.");
  const allEntries = asArray(tree.tree ?? tree, "candidate tree entries");
  for (const entry of allEntries) {
    const value = asObject(entry, "candidate tree entry");
    if (value.type !== "blob" && value.type !== "tree") {
      fail("candidate_tree_verification_unavailable", "Candidate tree contains an unsupported entry type.");
    }
  }
  const entries = allEntries.filter((entry) => entry.type === "blob");
  const expectedMap = Array.isArray(expectedTree)
    ? Object.fromEntries(expectedTree.map((entry) => [entry.path, { mode: entry.mode, sha256: entry.sha256 ?? entry.sha }]))
    : normalizeExpectedTreeMap(expectedTree);
  if (entries.length !== Object.keys(expectedMap).length) fail("candidate_tree_mismatch", "Prepared commit contains unexpected or missing files.");
  const digest = crypto.createHash("sha256");
  for (const entry of entries.sort((left, right) => compareSafePaths(String(left.path), String(right.path)))) {
    const filePath = boundedString(entry.path, "candidate tree path", 300);
    const expected = expectedMap[filePath];
    if (!expected || String(entry.mode) !== String(expected.mode)) fail("candidate_tree_mismatch", "Prepared commit contains an unexpected file entry.", { path: filePath });
    const blob = await apiCall(api, auth, "getBlob", [entry.sha]);
    if (blob.encoding !== "base64" || typeof blob.content !== "string") fail("candidate_tree_verification_unavailable", "GitHub blob content is not base64 encoded.");
    const content = Buffer.from(blob.content.replace(/\n/g, ""), "base64");
    if (sha256(content) !== expected.sha256) fail("candidate_tree_mismatch", "Prepared commit file content differs from the expected tree.", { path: filePath });
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(content.length));
    digest.update(filePath).update("\0").update(String(entry.mode)).update("\0").update(length).update(content);
  }
  if (digest.digest("hex") !== expectedDigest) fail("candidate_tree_mismatch", "Prepared commit tree does not match the immutable expected tree.");
  // Changed candidate content must also be present in the exact remote tree;
  // this catches a commit API response that points at an older base.
  for (const file of candidateFiles) {
    const expected = expectedMap[file.path];
    if (!expected || expected.sha256 !== sha256(file.content)) fail("candidate_tree_mismatch", "Prepared commit omitted an expected changed file.", { path: file.path });
  }
  return { treeSha, expectedDigest };
}

async function verifyPreparedCommit(api, auth, state) {
  const preparedCommitSha = normalizeSha(state.preparedCommitSha, "prepared commit SHA");
  const preparedTreeSha = normalizeSha(state.preparedTreeSha, "prepared tree SHA");
  const baseSha = normalizeSha(state.baseSha, "base SHA");
  const commit = await apiCall(api, auth, "getCommit", [preparedCommitSha]);
  const actualTreeSha = normalizeSha(commit.tree?.sha ?? commit.treeSha, "prepared commit tree SHA");
  if (actualTreeSha !== preparedTreeSha) {
    fail("candidate_identity_mismatch", "Prepared commit tree does not match the durable preparation intent.");
  }
  const parents = asArray(commit.parents, "prepared commit parents");
  if (parents.length !== 1 || normalizeSha(parents[0]?.sha, "prepared commit parent SHA") !== baseSha) {
    fail("candidate_identity_mismatch", "Prepared commit parent does not match the durable preparation intent.");
  }
  await verifyCandidateTree(
    api,
    auth,
    preparedCommitSha,
    state.expectedTree.digest,
    state.expectedTree.files,
    state.candidateFiles,
  );
  return { commitSha: preparedCommitSha, treeSha: preparedTreeSha };
}

function releaseNotesFromEvidence(evidence) {
  const notes = evidence.candidateFiles?.find((file) => file.path === evidence.notesPath)?.content;
  if (typeof notes !== "string" || !notes.includes("Automatically generated from repository history. Not editorially reviewed.")) {
    fail("notes_invalid", "Immutable preparer notes are unavailable or missing the required disclaimer.");
  }
  return notes;
}

export function assertReleaseMetadata(release, { tag, mergedSha, notes, draft, code = "release_conflict" } = {}) {
  const value = asObject(release, "GitHub release");
  const releaseId = normalizePositiveInteger(value.id, "GitHub release ID");
  const expectedTag = boundedString(tag, "release tag", 100);
  if (value.tag_name !== expectedTag) fail(code, "GitHub release tag does not match the immutable release intent.");
  let targetSha;
  try {
    targetSha = normalizeSha(value.target_commitish, "release target commit");
  } catch {
    fail(code, "GitHub release target does not match the accepted merged commit.");
  }
  if (targetSha !== normalizeSha(mergedSha, "merged SHA")) {
    fail(code, "GitHub release target does not match the accepted merged commit.");
  }
  if (typeof value.body !== "string" || value.body !== notes) {
    fail(code, "GitHub release notes do not match the immutable release intent.");
  }
  if (typeof value.prerelease !== "boolean" || value.prerelease !== false) {
    fail(code, "GitHub release prerelease metadata is not the approved stable value.");
  }
  if (typeof value.draft !== "boolean") fail(code, "GitHub release draft metadata is malformed.");
  if (draft !== undefined && value.draft !== draft) fail(code, "GitHub release draft state does not match the immutable release intent.");
  return { ...value, id: releaseId };
}

async function findReleaseByTag(api, auth, tag) {
  if (typeof api?.listReleases !== "function") {
    fail("release_metadata_unavailable", "Release listing is required to reconcile drafts and published releases.");
  }
  const response = await apiCall(api, auth, "listReleases", []);
  const releases = collectionItems(response, "releases", "releases");
  const matches = releases.filter((release) => release?.tag_name === tag);
  if (matches.length > 1) fail("release_ambiguous", "Multiple GitHub releases claim the immutable stable tag.");
  return matches[0];
}

async function readReleaseById(api, auth, release, expected) {
  if (typeof api?.getRelease !== "function") fail("release_metadata_unavailable", "Release read-back is required before publication.");
  const id = normalizePositiveInteger(release?.id, "GitHub release ID");
  const value = await apiCall(api, auth, "getRelease", [id]);
  return assertReleaseMetadata(value, { ...expected, code: "release_readback_mismatch" });
}

async function readTagTargetIfPresent(api, auth, tag) {
  try {
    return await resolveTagCommitSha(api, auth, tag);
  } catch (error) {
    if (error instanceof ReleaseAutomationError && error.code === "github_api_error" && error.details?.status === 404) return undefined;
    throw error;
  }
}

function isStableTag(value) {
  return typeof value === "string" && /^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/.test(value);
}

async function resolveTagCommitSha(api, auth, tag) {
  const ref = await apiCall(api, auth, "getTagRef", [tag]);
  const reference = asObject(ref, "tag reference");
  const object = asObject(reference.object, "tag reference object");
  let type = object.type;
  let sha = normalizeSha(object.sha, "tag reference SHA");
  for (let depth = 0; depth < MAX_ANNOTATED_TAG_DEPTH; depth += 1) {
    if (type === "commit") return sha;
    if (type !== "tag") fail("tag_identity_mismatch", "Stable tag reference does not resolve to a commit or annotated tag.");
    const tagObject = asObject(await apiCall(api, auth, "getTag", [sha]), "annotated tag object");
    const target = asObject(tagObject.object, "annotated tag target");
    type = target.type;
    sha = normalizeSha(target.sha, "annotated tag target SHA");
  }
  fail("tag_identity_mismatch", "Annotated stable tag exceeds the bounded peel depth.");
}

export async function readLatestStable(api, auth) {
  const releases = await apiCall(api, auth, "listReleases", []);
  const candidates = collectionItems(releases, "releases", "releases")
    // A missing flag is not evidence of a published stable release. GitHub's
    // release DTO supplies both booleans; require the exact published shape
    // before using its tag as the version baseline.
    .filter((release) => release?.draft === false && release?.prerelease === false && isStableTag(release?.tag_name))
    .sort((left, right) => compareStableVersions(right.tag_name.slice(1), left.tag_name.slice(1)));
  if (candidates.length === 0) return undefined;
  const release = candidates[0];
  const targetSha = await resolveTagCommitSha(api, auth, release.tag_name);
  return {
    tag: release.tag_name,
    version: release.tag_name.slice(1),
    sha: targetSha,
    release,
  };
}

async function reconcileExistingTag(api, auth, tag, expectedSha) {
  try {
    const targetSha = await resolveTagCommitSha(api, auth, tag);
    if (expectedSha && targetSha !== normalizeSha(expectedSha)) fail("tag_conflict", `Existing ${tag} tag points to a different commit.`);
    return { exists: true, sha: targetSha };
  } catch (error) {
    if (error instanceof ReleaseAutomationError && error.code === "github_api_error" && error.details?.status === 404) return { exists: false };
    throw error;
  }
}

export async function checkMainPublication(api, auth, mergedSha, options = {}) {
  const normalizedSha = normalizeSha(mergedSha, "merged SHA");
  const runsResponse = await apiCall(api, auth, "getWorkflowRuns", [{
    headSha: normalizedSha,
    event: "push",
    branch: "main",
    workflow: CI_WORKFLOW_PATH,
  }]);
  const runs = collectionItems(runsResponse, "workflow_runs", "main workflow runs");
  const verification = selectWorkflowRun(runs, {
    headSha: normalizedSha,
    repository: options.repository,
    repositoryId: options.repositoryId,
    event: "push",
    workflowPath: CI_WORKFLOW_PATH,
    requireMainBranch: true,
  });
  if (!verification) return { state: "pending" };
  const runResult = workflowRunState(verification.value);
  if (runResult === "failed") return { state: "failed", verification: verification.value };
  const jobsResponse = await apiCall(api, auth, "getWorkflowRunJobs", [verification.runId, verification.runAttempt]);
  const jobs = collectionItems(jobsResponse, "jobs", "main workflow jobs");
  const jobResult = jobsForWorkflowRun(jobs, verification, normalizedSha, { includeEdge: true });
  if (jobResult.failures.length > 0) return { state: "failed", verification: verification.value, edge: jobResult.edge, statuses: jobResult.statuses, failures: jobResult.failures };
  if (jobResult.pending || runResult === "pending") {
    if (runResult === "success") {
      // A completed successful run can never produce the missing job later, so
      // absent main or edge evidence is a permanent failure, not a pending wait.
      const missing = Object.entries(jobResult.statuses)
        .filter(([, value]) => value === "missing")
        .map(([context]) => ({ context, reason: "missing" }));
      if (missing.length > 0) {
        return { state: "failed", verification: verification.value, edge: jobResult.edge, statuses: jobResult.statuses, failures: missing };
      }
    }
    return { state: "pending", verification: verification.value, edge: jobResult.edge, statuses: jobResult.statuses };
  }
  return { state: "passed", verification: verification.value, edge: jobResult.edge, statuses: jobResult.statuses };
}

function normalizeImageDigest(value, label = "image digest") {
  if (typeof value !== "string" || !IMAGE_DIGEST_PATTERN.test(value)) fail("publication_digest_mismatch", `${label} must be a sha256:<digest> value.`);
  return value.toLowerCase();
}

function exactPlatformNames(value, label) {
  const platforms = asArray(value, label).map((item) => {
    if (typeof item === "string") return item;
    if (item && typeof item.name === "string") return item.name;
    fail("publication_incomplete", `${label} contains an invalid platform.`);
  });
  const expected = ["linux/amd64", "linux/arm64"];
  if (platforms.length !== expected.length || new Set(platforms).size !== platforms.length || expected.some((platform) => !platforms.includes(platform))) {
    fail("publication_incomplete", `${label} must contain linux/amd64 and linux/arm64 exactly once.`);
  }
  return expected;
}

function assertPublicationUrl(value, expected, label) {
  const url = boundedString(value, label, 500);
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    fail("publication_provenance_mismatch", `${label} is malformed.`);
  }
  if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) fail("publication_provenance_mismatch", `${label} is not a trusted HTTPS URL.`);
  if (expected !== undefined && url !== expected) fail("publication_provenance_mismatch", `${label} does not identify the selected workflow or release.`);
  return url;
}

export function validatePublicationEvidence(evidence, {
  repository,
  version,
  mergedSha,
  runId,
  releaseURL,
} = {}) {
  const value = asObject(evidence, "publication evidence");
  if (value.schemaVersion !== 1 || value.operation !== "stable-image-publication") fail("publication_schema_invalid", "Stable publication evidence schema is unsupported.");
  if (!["published", "repaired", "reused"].includes(value.state)) fail("publication_incomplete", "Stable publication state is not a canonical publisher state.");
  const expectedVersion = parseStableVersion(version, "publication version").text;
  const expectedReleaseTag = releaseTag(expectedVersion);
  if (value.version !== expectedVersion || value.releaseTag !== expectedReleaseTag) fail("publication_provenance_mismatch", "Publication version and tag do not match the selected release.");
  const expectedRevision = normalizeSha(mergedSha, "merged SHA");
  if (normalizeSha(value.sourceRevision, "publication source revision") !== expectedRevision) fail("publication_provenance_mismatch", "Published image source revision does not match the merged SHA.");
  const digest = normalizeImageDigest(value.digest, "publication digest");
  const expectedImage = repository ? `ghcr.io/${normalizeRepository(repository)}` : undefined;
  if (expectedImage !== undefined && value.image !== expectedImage) fail("publication_provenance_mismatch", "Publication image does not match the target repository.");
  if (typeof value.image !== "string" || !/^ghcr\.io\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(value.image)) fail("publication_provenance_mismatch", "Publication image is malformed.");
  if (Object.prototype.hasOwnProperty.call(value, "tags")) fail("publication_schema_invalid", "Publication evidence must use canonical actualTags.");
  const actualTags = asArray(value.actualTags, "publication actualTags");
  const expectedTags = [expectedReleaseTag, minorTag(expectedVersion), "latest"];
  if (actualTags.length !== expectedTags.length) fail("publication_incomplete", "Publication actualTags must contain exactly the three stable tags.");
  const seenTags = new Set();
  for (const expectedTag of expectedTags) {
    const tag = actualTags.find((item) => item?.name === expectedTag);
    if (!tag || seenTags.has(expectedTag)) fail("publication_incomplete", `Publication is missing the ${expectedTag} tag.`);
    seenTags.add(expectedTag);
    const entry = asObject(tag, "publication tag");
    if (entry.tag !== expectedTag || entry.reference !== `${value.image}:${expectedTag}`) fail("publication_provenance_mismatch", `Publication tag ${expectedTag} has an unexpected reference.`);
    if (normalizeImageDigest(entry.digest, `publication ${expectedTag} digest`) !== digest) fail("publication_digest_mismatch", `Publication tag ${expectedTag} has a different digest.`);
    if (normalizeSha(entry.sourceRevision, `publication ${expectedTag} source revision`) !== expectedRevision) fail("publication_provenance_mismatch", `Publication tag ${expectedTag} has a different source revision.`);
    exactPlatformNames(entry.platforms, `publication ${expectedTag} platforms`);
  }
  const platforms = exactPlatformNames(value.platforms, "publication platforms");
  const expectedWorkflowURL = repository && runId !== undefined ? `https://github.com/${normalizeRepository(repository)}/actions/runs/${normalizeRunId(runId)}` : undefined;
  const expectedReleaseURL = releaseURL ?? (repository ? `https://github.com/${normalizeRepository(repository)}/releases/tag/${expectedReleaseTag}` : undefined);
  const workflowURL = assertPublicationUrl(value.workflowURL, expectedWorkflowURL, "publication workflow URL");
  const checkedReleaseURL = assertPublicationUrl(value.releaseURL, expectedReleaseURL, "publication release URL");
  return {
    schemaVersion: 1,
    operation: "stable-image-publication",
    state: value.state,
    image: value.image,
    version: expectedVersion,
    releaseTag: expectedReleaseTag,
    sourceRevision: expectedRevision,
    digest,
    platforms,
    actualTags,
    workflowURL,
    releaseURL: checkedReleaseURL,
  };
}

export async function waitForPublication(api, auth, artifacts, publisher, state, options = {}) {
  const clock = normalizeClock(options.clock);
  const result = await pollUntil(
    async () => {
      const runsResponse = await apiCall(api, auth, "getWorkflowRuns", [{
        headSha: state.mergedSha,
        event: "release",
        workflow: RELEASE_WORKFLOW_PATH,
      }]);
      const runs = collectionItems(runsResponse, "workflow_runs", "release workflow runs");
      const selected = selectWorkflowRun(runs, {
        headSha: state.mergedSha,
        repository: state.repository,
        repositoryId: state.repositoryId,
        event: "release",
        workflowPath: RELEASE_WORKFLOW_PATH,
      });
      if (!selected) return { state: "pending" };
      const runState = workflowRunState(selected.value);
      if (runState === "failed") return { state: "failed", run: selected.value };
      if (runState === "pending") return { state: "pending", run: selected.value };
      if (!artifacts || typeof artifacts.read !== "function") fail("artifact_reader_unavailable", "Stable publication artifact reader is unavailable.");
      if (typeof api.listRunArtifacts !== "function" || typeof api.getArtifact !== "function") fail("artifact_metadata_unavailable", "Stable publication artifact metadata endpoints are unavailable.");
      const artifactResponse = await apiCall(api, auth, "listRunArtifacts", [selected.runId]);
      const artifactItems = collectionItems(artifactResponse, "artifacts", "stable publication artifacts");
      const artifactName = `stable-publication-evidence-${selected.runId}-${selected.runAttempt}`;
      const matches = artifactItems.filter((item) => item?.name === artifactName);
      if (matches.length > 1) fail("artifact_identity_mismatch", "Multiple stable publication evidence artifacts match the release workflow attempt.");
      if (matches.length === 0) return { state: "pending", run: selected.value };
      const hint = asObject(matches[0], "stable publication artifact listing");
      const artifactId = normalizePositiveInteger(hint.id, "stable publication artifact ID");
      const metadataResponse = await apiCall(api, auth, "getArtifact", [artifactId]);
      const metadata = asObject(metadataResponse?.artifact ?? metadataResponse, "stable publication artifact metadata");
      const record = validateArtifactMetadata(metadata, {
        id: artifactId,
        name: artifactName,
        digest: hint.digest,
        runId: selected.runId,
        repository: state.repository,
        repositoryId: state.repositoryId,
        headSha: state.mergedSha,
      }, clock.now());
      const downloaded = await artifacts.read(record.id, {
        digest: record.digest,
        expectedFilename: "release-publication-evidence.json",
        workflowRunId: selected.runId,
      });
      let publication = downloaded;
      if (Buffer.isBuffer(publication)) publication = JSON.parse(publication.toString("utf8"));
      if (typeof publication === "string") publication = JSON.parse(publication);
      return { state: "passed", run: selected.value, artifact: record, publication };
    },
    { ...options, clock, label: "stable publication" },
  );
  if (result.state !== "passed") return result;
  const publication = validatePublicationEvidence(result.publication, {
    repository: state.repository,
    version: state.version,
    mergedSha: state.mergedSha,
    runId: result.run?.id,
    releaseURL: state.releaseUrl,
  });
  return { ...result, publication };
}

async function writeJsonFile(filePath, value) {
  await fsp.mkdir(path.dirname(filePath), { recursive: true });
  await fsp.writeFile(filePath, `${canonicalJson(value)}\n`, { encoding: "utf8", mode: 0o600 });
}

function defaultContext(environment = process.env) {
  let event = {};
  if (environment.GITHUB_EVENT_PATH) {
    try {
      event = JSON.parse(fs.readFileSync(environment.GITHUB_EVENT_PATH, "utf8"));
    } catch {
      fail("untrusted_trigger", "GitHub event payload is missing or malformed.");
    }
  }
  return {
    eventName: environment.GITHUB_EVENT_NAME,
    ref: environment.GITHUB_REF,
    repository: environment.GITHUB_REPOSITORY,
    actor: environment.GITHUB_ACTOR,
    sha: environment.GITHUB_SHA,
    runId: environment.GITHUB_RUN_ID,
    runAttempt: environment.GITHUB_RUN_ATTEMPT,
    event,
  };
}

export async function runCredentialFreePreparer({
  scriptPath = path.resolve("scripts/prepare-release.py"),
  python = process.env.PYTHON ?? "python3",
  cwd = process.cwd(),
  input,
  timeoutMs = DEFAULT_PREPARER_TIMEOUT_MS,
  environment = process.env,
} = {}) {
  if (!fs.existsSync(scriptPath)) fail("preparer_unavailable", "Deterministic release preparer is unavailable.");
  ensureSafeEvidenceValue(input, "preparer input");
  const temporary = await fsp.mkdtemp(path.join(os.tmpdir(), "media-finder-release-preparer-"));
  const inputPath = path.join(temporary, "snapshot.json");
  const outputPath = path.join(temporary, "output.json");
  const snapshot = input.notesInputSnapshot ?? input.snapshot;
  if (!snapshot) fail("preparer_input_invalid", "Preparer requires an immutable captured snapshot.");
  await writeJsonFile(inputPath, snapshot);
  const cleanEnvironment = sanitizeCredentialEnvironment(environment);
  try {
    const result = await execFileAsync(python, [
      scriptPath,
      "--root",
      cwd,
      "--version",
      boundedString(input.version, "preparer version", 40),
      "--snapshot",
      inputPath,
      "--result",
      outputPath,
    ], {
      cwd,
      env: cleanEnvironment,
      timeout: timeoutMs,
      maxBuffer: MAX_RESPONSE_BYTES,
      shell: false,
    });
    let raw;
    if (fs.existsSync(outputPath)) raw = JSON.parse(await fsp.readFile(outputPath, "utf8"));
    else raw = JSON.parse(result.stdout);
    return asObject(raw, "preparer output");
  } catch (error) {
    if (error instanceof ReleaseAutomationError) throw error;
    fail("preparer_failed", "Deterministic release preparation failed.");
  } finally {
    await fsp.rm(temporary, { recursive: true, force: true });
  }
}

async function defaultAuthenticator(environment, repository) {
  return new GitHubAppAuthenticator({
    appId: environment.RELEASE_APP_ID ?? environment.RELEASE_APP_CLIENT_ID,
    privateKey: environment.RELEASE_APP_PRIVATE_KEY,
    installationId: environment.RELEASE_APP_INSTALLATION_ID,
    expectedRepositoryId: environment.RELEASE_REPOSITORY_ID,
    repository,
  });
}

function currentVersionFromWorkspace(cwd = process.cwd()) {
  const file = path.join(cwd, "VERSION");
  try {
    return fs.readFileSync(file, "utf8").trim();
  } catch {
    fail("current_version_unavailable", "Workspace VERSION file is unavailable.");
  }
}

async function computeWorkingTreeDigest(cwd) {
  let output;
  try {
    ({ stdout: output } = await execFileAsync("git", ["-C", cwd, "ls-files", "-z"], {
      encoding: "buffer",
      maxBuffer: MAX_RESPONSE_BYTES,
      shell: false,
    }));
  } catch {
    fail("base_tree_digest_unavailable", "The trusted controller checkout cannot enumerate its Git tree.");
  }
  const paths = output.toString("utf8").split("\0").filter(Boolean).sort(compareSafePaths);
  if (paths.length === 0 || paths.length > MAX_TRACKED_FILES) fail("base_tree_digest_unavailable", "The trusted controller checkout has an invalid tracked-file set.");
  const digest = crypto.createHash("sha256");
  let totalBytes = 0;
  for (const filePath of paths) {
    if (!SAFE_PATH_PATTERN.test(filePath)) fail("base_tree_digest_unavailable", "The trusted controller checkout contains an unsafe tracked path.");
    const absolute = path.resolve(cwd, filePath);
    if (!absolute.startsWith(`${path.resolve(cwd)}${path.sep}`)) fail("base_tree_digest_unavailable", "The trusted controller checkout escapes its root.");
    let stat;
    let content;
    try {
      stat = await fsp.lstat(absolute);
      if (!stat.isFile() || stat.isSymbolicLink()) fail("base_tree_digest_unavailable", "The trusted controller checkout contains a non-regular tracked path.", { path: filePath });
      content = await fsp.readFile(absolute);
    } catch (error) {
      if (error instanceof ReleaseAutomationError) throw error;
      fail("base_tree_digest_unavailable", "The trusted controller checkout contains an unreadable tracked path.", { path: filePath });
    }
    totalBytes += content.length;
    if (totalBytes > MAX_WORKTREE_BYTES) fail("base_tree_digest_unavailable", "The trusted controller checkout exceeds the bounded tree digest limit.");
    const mode = stat.mode & 0o111 ? "100755" : "100644";
    digest.update(filePath).update("\0").update(mode).update("\0");
    const length = Buffer.alloc(8);
    length.writeBigUInt64BE(BigInt(content.length));
    digest.update(length).update(content);
  }
  return digest.digest("hex");
}

async function captureCompleteHistory(api, auth, previousStableTag, baseSha, repository) {
  const commits = [];
  const seen = new Set();
  let declaredTotal;
  for (let page = 1; page <= MAX_HISTORY_PAGES; page += 1) {
    const comparison = asObject(
      await apiCall(api, auth, "compareCommits", [previousStableTag, baseSha, { page, perPage: HISTORY_PAGE_SIZE }]),
      "release history comparison",
    );
    if (comparison.total_commits !== undefined) {
      const total = Number(comparison.total_commits);
      if (!Number.isSafeInteger(total) || total < 0) fail("history_input_invalid", "GitHub reported a malformed release history total.");
      if (declaredTotal === undefined) {
        if (total > MAX_HISTORY_COMMITS) {
          fail("history_bound_exceeded", "Release history exceeds the bounded capture limit; history cannot be truncated silently.", {
            total,
            bound: MAX_HISTORY_COMMITS,
          });
        }
        declaredTotal = total;
      } else if (total !== declaredTotal) {
        fail("history_incomplete", "Release history changed while it was being captured.");
      }
    }
    const pageCommits = asArray(comparison.commits ?? [], "release history commits");
    if (pageCommits.length > HISTORY_PAGE_SIZE) {
      fail("history_incomplete", "GitHub returned more history commits than the requested page size.");
    }
    for (const commit of pageCommits) {
      const value = asObject(commit, "release history commit");
      const sha = normalizeSha(value.sha, "history commit SHA");
      if (seen.has(sha)) fail("history_incomplete", "Release history pagination repeated a commit.");
      seen.add(sha);
      commits.push({ sha, url: boundedRepositoryUrl(repository, commit.html_url ?? commit.url, "history commit URL") });
    }
    if (commits.length > MAX_HISTORY_COMMITS) {
      fail("history_bound_exceeded", "Release history exceeds the bounded capture limit; history cannot be truncated silently.", {
        collected: commits.length,
        bound: MAX_HISTORY_COMMITS,
      });
    }
    if (pageCommits.length < HISTORY_PAGE_SIZE) {
      // A short page is the provider's own end-of-history signal. When the
      // provider also declares a total, both must agree exactly.
      if (declaredTotal !== undefined && commits.length !== declaredTotal) {
        fail("history_incomplete", "Release history capture did not return the declared commit count.", {
          declared: declaredTotal,
          collected: commits.length,
        });
      }
      return commits;
    }
    if (declaredTotal !== undefined && commits.length >= declaredTotal) {
      if (commits.length > declaredTotal) fail("history_incomplete", "Release history capture returned more commits than declared.");
      return commits;
    }
  }
  fail("history_incomplete", "Release history pagination exceeded the bounded page count.", { bound: MAX_HISTORY_PAGES });
}

async function captureHistory(api, auth, previousStableTag, baseSha, repository, requestedVersion, baseTreeDigest) {
  if (typeof api.captureReleaseInputs === "function") {
    const snapshot = await apiCall(api, auth, "captureReleaseInputs", [{ previousStableTag, baseSha, repository, requestedVersion }]);
    ensureSafeEvidenceValue(snapshot, "notesInputSnapshot");
    return snapshot;
  }
  const repositoryInfo = await apiCall(api, auth, "getRepository", []);
  const baseCommit = await apiCall(api, auth, "getCommit", [baseSha]);
  normalizeSha(baseCommit.tree?.sha ?? baseCommit.treeSha, "base Git tree SHA");
  const trustedBaseTreeDigest = normalizeDigest(baseTreeDigest, "base tree digest");
  const previousSha = await resolveTagCommitSha(api, auth, previousStableTag);
  const commits = await captureCompleteHistory(api, auth, previousStableTag, baseSha, repository);
  const pullRequests = [];
  const seenPullRequests = new Set();
  if (typeof api.getCommitPullRequests === "function") {
    for (const commit of commits) {
      const links = asArray(await apiCall(api, auth, "getCommitPullRequests", [commit.sha]), "commit pull requests");
      for (const pull of links) {
        const number = Number(pull.number);
        if (!Number.isSafeInteger(number) || number < 1 || number > 1_000_000_000 || seenPullRequests.has(number)) continue;
        const url = boundedRepositoryUrl(repository, pull.html_url ?? pull.url, "pull request URL");
        seenPullRequests.add(number);
        pullRequests.push({ number, url });
      }
    }
  }
  return {
    schema_version: 1,
    repository: {
      name: repository,
      url: `https://github.com/${repository}`,
    },
    base: {
      commit: normalizeSha(baseSha),
      tree_sha256: trustedBaseTreeDigest,
    },
    requested_version: requestedVersion,
    previous_stable: {
      tag: previousStableTag,
      sha: previousSha,
      url: `https://github.com/${repository}/releases/tag/${previousStableTag}`,
    },
    history: { commits, pull_requests: pullRequests },
  };
}

/**
 * Create a clean checkout of the recorded base commit on a path that never
 * holds write credentials. `git worktree` shares the trusted controller's
 * object database while keeping a separate, empty working directory, so no
 * candidate content and no credential ever reaches the source checkout.
 */
export async function createCleanBaseCheckout({ sourceCwd = process.cwd(), baseSha, temporaryDirectory } = {}) {
  const base = normalizeSha(baseSha, "recorded base SHA");
  const repositoryRoot = path.resolve(sourceCwd);
  const parent = path.resolve(temporaryDirectory ?? os.tmpdir());
  await fsp.mkdir(parent, { recursive: true, mode: 0o700 });
  const checkoutRoot = await fsp.mkdtemp(path.join(parent, "media-finder-release-base-"));
  // `git worktree add` requires an empty or non-existent target directory.
  await fsp.rm(checkoutRoot, { recursive: true, force: true });
  const environment = sanitizeCredentialEnvironment(process.env);
  const runGit = async (arguments_) => {
    try {
      return await execFileAsync("git", ["-C", repositoryRoot, ...arguments_], {
        env: environment,
        shell: false,
        maxBuffer: MAX_RESPONSE_BYTES,
        encoding: "utf8",
      });
    } catch {
      fail("regeneration_checkout_unavailable", "The clean base checkout could not be created or inspected.");
    }
  };
  const cleanup = async () => {
    try {
      await execFileAsync("git", ["-C", repositoryRoot, "worktree", "remove", "--force", checkoutRoot], {
        env: environment,
        shell: false,
        maxBuffer: MAX_RESPONSE_BYTES,
      });
    } catch {
      // The worktree may already be gone; fall through to direct removal.
    }
    try {
      await execFileAsync("git", ["-C", repositoryRoot, "worktree", "prune"], { env: environment, shell: false, maxBuffer: MAX_RESPONSE_BYTES });
    } catch {
      // Pruning is best effort; the checkout itself is still removed below.
    }
    await fsp.rm(checkoutRoot, { recursive: true, force: true });
  };
  try {
    await runGit(["worktree", "add", "--detach", checkoutRoot, base]);
    const head = (await runGit(["-C", checkoutRoot, "rev-parse", "HEAD"])).stdout.trim();
    if (normalizeSha(head, "clean checkout HEAD") !== base) {
      fail("regeneration_checkout_invalid", "The clean checkout is not at the recorded base commit.");
    }
    const status = (await runGit(["-C", checkoutRoot, "status", "--porcelain"])).stdout;
    if (status.trim() !== "") fail("regeneration_checkout_invalid", "The clean checkout of the recorded base is not clean.");
  } catch (error) {
    await cleanup();
    throw error;
  }
  return { root: checkoutRoot, cleanup };
}

function assertReproducedCandidateTree(evidence, prepared, { baseSha, version, snapshot }) {
  const mismatch = (message, details = {}) => fail("candidate_regeneration_mismatch", message, details);
  if (prepared.version !== version) mismatch("Regenerated candidate version differs from the recorded version.");
  if (prepared.baseCommit !== baseSha) mismatch("Regenerated candidate base differs from the recorded base commit.");
  if (prepared.previousStableTag !== boundedString(evidence.previousStableTag, "recorded previous stable tag", 100)) {
    mismatch("Regenerated candidate previous stable tag differs from the recorded tag.");
  }
  if (prepared.previousStableSha !== normalizeSha(evidence.previousStableSha, "recorded previous stable SHA")) {
    mismatch("Regenerated candidate previous stable commit differs from the recorded commit.");
  }
  if (prepared.snapshotSha256 !== sha256(`${canonicalJson(snapshot)}\n`)) {
    mismatch("Regeneration did not consume the recorded captured release inputs.");
  }
  const recordedTree = normalizeExpectedTreeMap(evidence.expectedTree?.files);
  const producedTree = prepared.expectedTree;
  const recordedPaths = Object.keys(recordedTree);
  const producedPaths = Object.keys(producedTree);
  if (recordedPaths.length !== producedPaths.length || recordedPaths.some((filePath, index) => filePath !== producedPaths[index])) {
    mismatch("Regenerated candidate tree does not contain the recorded file set.", {
      recordedFiles: recordedPaths.length,
      producedFiles: producedPaths.length,
    });
  }
  for (const filePath of recordedPaths) {
    if (recordedTree[filePath].mode !== producedTree[filePath].mode || recordedTree[filePath].sha256 !== producedTree[filePath].sha256) {
      mismatch("Regenerated candidate content differs from the recorded immutable tree.", { path: filePath });
    }
  }
  const recordedDigest = normalizeDigest(evidence.candidateTreeSha256 ?? evidence.expectedTree?.digest, "recorded candidate tree digest");
  if (prepared.candidateTreeSha256 !== recordedDigest) {
    mismatch("Regenerated candidate tree digest differs from the recorded immutable tree.");
  }
  const recordedFiles = normalizeCandidateFiles(evidence.candidateFiles);
  if (recordedFiles.length !== prepared.changedFiles.length) {
    mismatch("Regenerated candidate changed-file set differs from the recorded candidate.");
  }
  for (const [index, recorded] of recordedFiles.entries()) {
    const produced = prepared.changedFiles[index];
    if (recorded.path !== produced.path || recorded.mode !== produced.mode || sha256(recorded.content) !== sha256(produced.content)) {
      mismatch("Regenerated candidate changed-file content differs from the recorded candidate.", { path: recorded.path });
    }
  }
  return true;
}

/**
 * Reproduce the entire recorded candidate tree from the recorded base, the
 * requested version and the captured snapshot by running the credential-free
 * preparer in a clean checkout of the recorded base. Any difference from the
 * recorded expected tree is refused.
 */
export async function reproduceCandidateTree({
  state,
  cwd = process.cwd(),
  preparer,
  environment = process.env,
  scriptPath,
  python,
  timeoutMs,
  temporaryDirectory,
} = {}) {
  const evidence = asObject(state, "release state");
  const baseSha = normalizeSha(evidence.baseSha, "recorded base SHA");
  const version = parseStableVersion(evidence.version, "recorded version").text;
  const snapshot = evidence.notesInputSnapshot;
  if (snapshot === null || typeof snapshot !== "object" || Array.isArray(snapshot)) {
    fail("regeneration_input_missing", "The captured release inputs are required to reproduce the candidate tree.");
  }
  const input = {
    repository: normalizeRepository(evidence.repository),
    baseSha,
    version,
    previousStableTag: boundedString(evidence.previousStableTag, "recorded previous stable tag", 100),
    previousStableSha: normalizeSha(evidence.previousStableSha, "recorded previous stable SHA"),
    notesInputSnapshot: snapshot,
  };
  const checkout = typeof preparer?.createCheckout === "function"
    ? await preparer.createCheckout({ baseSha, sourceCwd: cwd })
    : await createCleanBaseCheckout({ sourceCwd: cwd, baseSha, temporaryDirectory });
  if (!checkout || typeof checkout.root !== "string" || checkout.root.length === 0) {
    fail("regeneration_checkout_unavailable", "The clean checkout of the recorded base is unavailable.");
  }
  try {
    const raw = typeof preparer?.prepare === "function"
      ? await preparer.prepare({ root: checkout.root, version, snapshot, ...input })
      : await runCredentialFreePreparer({
        cwd: checkout.root,
        input,
        environment,
        ...(scriptPath === undefined ? {} : { scriptPath }),
        ...(python === undefined ? {} : { python }),
        ...(timeoutMs === undefined ? {} : { timeoutMs }),
      });
    if (!raw) fail("regeneration_failed", "The credential-free preparer returned no output while reproducing the candidate tree.");
    const prepared = candidateFilesFromPreparationResult(raw, checkout.root);
    assertReproducedCandidateTree(evidence, prepared, { baseSha, version, snapshot });
    return {
      version,
      baseSha,
      candidateFiles: prepared.changedFiles,
      expectedTree: prepared.expectedTree,
      candidateTreeSha256: prepared.candidateTreeSha256,
    };
  } finally {
    if (typeof checkout.cleanup === "function") await checkout.cleanup();
  }
}

function boundedRepositoryUrl(repository, value, label) {
  const url = boundedString(value, label, 500);
  const parsed = new URL(url);
  if (parsed.protocol !== "https:" || parsed.hostname.toLowerCase() !== "github.com" || parsed.username || parsed.password || parsed.search || parsed.hash || !parsed.pathname.startsWith(`/${repository}/`)) fail("history_input_invalid", `${label} must be an HTTPS link in the captured repository.`);
  return url;
}

async function preparePhase({ api, auth, artifacts, context, input, config, preparer, cwd }) {
  // Preparation is bounded by the same operation-wide budget as the waits, so a
  // deadline that already elapsed stops before any candidate object is created.
  const preparationBudgetMs = config.budget === undefined ? undefined : config.budget.remaining("release preparation");
  validateDispatchContext(context, {
    repository: config.repository,
    allowedActors: config.allowedActors,
    trustedControllerSha: config.trustedControllerSha,
  });
  const repository = normalizeRepository(context.repository);
  const repositoryInfo = await apiCall(api, auth, "getRepository", []);
  if (String(repositoryInfo.full_name ?? "").toLowerCase() !== repository.toLowerCase()) fail("repository_mismatch", "GitHub repository identity does not match the workflow context.");
  const repositoryId = normalizePositiveInteger(repositoryInfo.id, "GitHub repository ID");
  if (config.repositoryId !== undefined && repositoryId !== normalizePositiveInteger(config.repositoryId, "configured repository ID")) fail("repository_scope_mismatch", "GitHub repository ID does not match trusted configuration.");
  if (!auth?.current?.identity) fail("app_identity_unavailable", "Authenticated App identity is unavailable.");
  if (auth.current.identity.repository.toLowerCase() !== repository.toLowerCase() || auth.current.identity.repositoryId !== repositoryId) {
    fail("repository_scope_mismatch", "Installation token identity does not match the GitHub repository.");
  }
  const main = await apiCall(api, auth, "getRef", ["heads/main"]);
  const baseSha = normalizeSha(main.object?.sha, "main SHA");
  if (context.sha && normalizeSha(context.sha, "workflow SHA") !== baseSha) fail("base_identity_mismatch", "Workflow SHA is not the current main commit.");
  const latest = await readLatestStable(api, auth);
  const requested = validateRequestedVersion(input.version, {
    currentVersion: input.currentVersion ?? currentVersionFromWorkspace(cwd),
    latestStableVersion: latest?.version,
  });
  if (!latest?.sha) fail("previous_release_unavailable", "Previous stable release commit could not be verified.");
  const operationId = input.operationId ?? operationIdFor({ repository, version: requested.text, originRunId: context.runId });
  const attempt = Number(input.attempt ?? 1);
  // Capture the exact mode-aware digest used by the credential-free Python
  // preparer from this trusted, clean-base checkout. This avoids an
  // unbounded blob-by-blob API walk while keeping the snapshot contract
  // identical to `prepare-release.py`.
  const baseTreeDigest = await computeWorkingTreeDigest(cwd);
  const notesInputSnapshot = input.notesInputSnapshot ?? await captureHistory(api, auth, latest.tag, baseSha, repository, requested.text, baseTreeDigest);
  const prepInput = {
    repository,
    baseSha,
    version: requested.text,
    previousStableTag: latest.tag,
    previousStableSha: latest.sha,
    notesInputSnapshot,
  };
  const rawPrepared = preparer
    ? await preparer.prepare?.({ root: cwd, version: requested.text, snapshot: notesInputSnapshot, ...prepInput })
    : await runCredentialFreePreparer({
      cwd,
      input: prepInput,
      environment: config.environment,
      ...(preparationBudgetMs === undefined ? {} : { timeoutMs: Math.min(DEFAULT_PREPARER_TIMEOUT_MS, preparationBudgetMs) }),
    });
  if (!rawPrepared) fail("preparer_failed", "Deterministic release preparer returned no output.");
  const prepared = candidateFilesFromPreparationResult(rawPrepared, cwd);
  const snapshotDigest = sha256(`${canonicalJson(notesInputSnapshot)}\n`);
  if (prepared.version !== requested.text || prepared.baseCommit !== baseSha || prepared.previousStableTag !== latest.tag || prepared.previousStableSha !== latest.sha || prepared.snapshotSha256 !== snapshotDigest || prepared.baseTreeSha256 !== baseTreeDigest) {
    fail("preparer_output_invalid", "Preparer output identities do not match the captured release intent.");
  }
  const normalizedFiles = prepared.changedFiles;
  const notesEntry = normalizedFiles.find((file) => file.path === prepared.notesPath);
  if (!notesEntry || !notesEntry.content.includes("Automatically generated from repository history. Not editorially reviewed.")) fail("notes_invalid", "Preparer notes are missing the required English disclaimer.");
  const withNotes = normalizedFiles;
  // GitHub's object API creates blobs, a tree, and a commit independently of
  // refs. Keep these objects unreachable until the immutable intent has been
  // uploaded and read back; a failed preparation therefore leaves no branch
  // or pull request to reconcile.
  const preparedObjects = await createCandidateCommit(api, auth, {
    baseSha,
    version: requested.text,
    candidateFiles: withNotes,
  });
  const evidence = buildPreparationEvidence({
    repository,
    repositoryId: Number(repositoryInfo.id),
    appId: auth?.current?.identity?.appId ?? Number(config.appId),
    installationId: auth?.current?.identity?.installationId ?? Number(config.installationId),
    operationId,
    attempt,
    trustedControllerSha: config.trustedControllerSha ?? context.sha,
    originRunId: context.runId,
    originRunAttempt: context.runAttempt,
    baseSha,
    previousStableTag: latest.tag,
    previousStableSha: latest.sha,
    version: requested.text,
    notesInputSnapshot,
    expectedTreeMap: prepared.expectedTree,
    candidateTreeSha256: prepared.candidateTreeSha256,
    candidateFiles: withNotes,
    notesPath: prepared.notesPath,
    preparedCommitSha: preparedObjects.commitSha,
    preparedTreeSha: preparedObjects.treeSha,
  });
  await verifyPreparedCommit(api, auth, evidence);
  const artifactWriter = config.artifactWriter;
  if (!artifactWriter || typeof artifactWriter.upload !== "function") {
    fail("artifact_writer_unavailable", "Immutable preparation evidence cannot be persisted before candidate exposure.");
  }
  const artifactName = `${operationId}-preparation-attempt-${attempt}`;
  const uploaded = await artifactWriter.upload({
    name: artifactName,
    content: `${canonicalJson(evidence)}\n`,
    retentionDays: PREPARATION_ARTIFACT_RETENTION_DAYS,
    overwrite: false,
  });
  const uploadedId = normalizePositiveInteger(uploaded?.id, "uploaded preparation artifact ID");
  const uploadedDigestValue = uploaded?.digest ?? uploaded?.artifact_digest;
  const uploadedDigest = uploadedDigestValue === undefined
    ? undefined
    : normalizeArtifactDigest(uploadedDigestValue, "uploaded preparation artifact digest");
  if (typeof api.getArtifact !== "function") fail("artifact_metadata_unavailable", "Immutable preparation artifact metadata cannot be verified.");
  const verifiedResponse = await apiCall(api, auth, "getArtifact", [uploadedId]);
  const verifiedMetadata = asObject(verifiedResponse?.artifact ?? verifiedResponse, "verified preparation artifact metadata");
  evidence.artifact = buildArtifactRecord(verifiedMetadata, {
    id: uploadedId,
    ...(uploadedDigest === undefined ? {} : { digest: uploadedDigest }),
    name: artifactName,
    repository,
    runId: context.runId,
    repositoryId,
    headSha: context.sha,
  });
  if (!artifacts || typeof artifacts.read !== "function") fail("artifact_reader_unavailable", "Immutable preparation artifact readback is unavailable.");
  const recoveredValue = await artifacts.read(evidence.artifact.id, {
    digest: evidence.artifact.digest,
    expectedFilename: "release-evidence.json",
    workflowRunId: context.runId,
  });
  let recovered = recoveredValue;
  if (Buffer.isBuffer(recovered)) recovered = JSON.parse(recovered.toString("utf8"));
  if (typeof recovered === "string") recovered = JSON.parse(recovered);
  const checkedRecovery = assertPreparationArtifact(recovered, {
    repository,
    trustedControllerSha: evidence.trustedControllerSha,
    originRunId: evidence.originRunId,
    originRunAttempt: evidence.originRunAttempt,
    version: evidence.version,
  });
  if (checkedRecovery.contentDigest !== evidence.contentDigest) fail("artifact_digest_mismatch", "Downloaded immutable preparation evidence does not match the prepared intent.");
  const statePath = config.statePath ?? path.join(cwd, ".release-automation", "preparation.json");
  await writeJsonFile(statePath, evidence);
  return { state: evidence, statePath };
}

async function loadAndVerifyPreparation({ api, auth, artifacts, state, input, config, context, clock }) {
  const evidence = assertPreparationArtifact(state, {
    repository: context.repository,
    // A recovery dispatch is allowed to run at a newer controller revision;
    // the immutable state's origin revision is the identity that must be
    // checked against its payload and provider metadata.
    trustedControllerSha: state.trustedControllerSha,
    originRunId: state.originRunId,
    originRunAttempt: state.originRunAttempt,
    version: input.version ?? state.version,
    now: clock.now(),
  });
  let authenticatedIdentity;
  if (auth?.current?.identity) {
    authenticatedIdentity = authenticatedAppIdentity(
      auth,
      context.repository,
      config.repositoryId ?? evidence.repositoryId,
    );
    assertPreparationAppIdentity(evidence, authenticatedIdentity);
  }
  if (typeof api?.getWorkflowRunAttempt !== "function") {
    fail("origin_run_unavailable", "The attempt-specific preparation workflow run endpoint is unavailable.");
  }
  const origin = await authenticatePreparationRun(api, auth, {
    id: evidence.originRunId,
    run_attempt: evidence.originRunAttempt,
  }, {
    repository: evidence.repository,
    repositoryId: evidence.repositoryId,
    allowedActors: config.allowedActors,
    runAttempt: evidence.originRunAttempt,
  });
  if (origin.headSha !== normalizeSha(evidence.trustedControllerSha, "trusted controller SHA")) {
    fail("controller_revision_mismatch", "Preparation origin revision does not match the immutable evidence.");
  }
  const artifactId = input.artifactId ?? state.artifact?.id ?? config.artifactId;
  const artifactDigest = input.artifactDigest ?? state.artifact?.digest ?? config.artifactDigest;
  if (!artifactId || !artifactDigest) fail("preparation_artifact_missing", "Immutable preparation artifact identity is required before exposing a candidate.");
  const metadata = await apiCall(api, auth, "getArtifact", [artifactId]);
  const record = validateArtifactMetadata(metadata, {
    id: artifactId,
    digest: artifactDigest,
    name: state.artifact?.name ?? `${state.operationId}-preparation-attempt-${state.attempt}`,
    runId: state.originRunId,
    repository: context.repository,
    repositoryId: evidence.repositoryId,
    headSha: evidence.trustedControllerSha,
  }, clock.now());
  if (record.workflowRunAttempt !== undefined && record.workflowRunAttempt !== evidence.originRunAttempt) {
    fail("artifact_provenance_mismatch", "Preparation artifact workflow attempt does not match the immutable evidence.");
  }
  if (!artifacts || typeof artifacts.read !== "function") fail("artifact_reader_unavailable", "Immutable preparation artifact reader is unavailable.");
  const downloaded = await artifacts.read(record.id, {
    digest: record.digest,
    expectedFilename: "release-evidence.json",
    workflowRunId: record.workflowRunId,
  });
  const recoveredValue = decodedArtifactValue(downloaded);
  const recovered = assertPreparationArtifact(recoveredValue, {
    repository: evidence.repository,
    trustedControllerSha: evidence.trustedControllerSha,
    originRunId: evidence.originRunId,
    originRunAttempt: evidence.originRunAttempt,
    version: evidence.version,
    now: clock.now(),
  });
  if (authenticatedIdentity) assertPreparationAppIdentity(recovered, authenticatedIdentity);
  if (recovered.contentDigest !== evidence.contentDigest) fail("artifact_digest_mismatch", "Downloaded immutable preparation evidence does not match the selected intent.");
  return { evidence, artifact: record };
}

async function ensureSameVersionConflict(api, auth, state, config) {
  if (typeof api.listPullRequests !== "function") return;
  const pulls = asArray(await apiCall(api, auth, "listPullRequests", [{ state: "open", base: "main" }]), "open pull requests");
  const active = pulls.filter((pr) => String(pr.head?.ref ?? "").startsWith("release-"));
  for (const pr of active) {
    if (Number(pr.number) === Number(state.prNumber)) continue;
    const activeVersion = releaseVersionFromRef(pr.head?.ref);
    if (activeVersion !== undefined && activeVersion !== state.version) fail("concurrent_release", "Another stable release operation is active.");
    if (activeVersion === state.version) fail("duplicate_release_state", "An authenticated same-version release operation already exists.");
  }
}

async function readCandidateRef(api, auth, branch) {
  try {
    const ref = await apiCall(api, auth, "getRef", [`heads/${branch}`]);
    const sha = normalizeSha(ref.object?.sha, "candidate branch SHA");
    return { exists: true, ref, sha };
  } catch (error) {
    if (error instanceof ReleaseAutomationError && error.code === "github_api_error" && error.details?.status === 404) {
      return { exists: false };
    }
    throw error;
  }
}

async function exposeCandidateRef(api, auth, branch, commitSha) {
  const expectedSha = normalizeSha(commitSha, "prepared commit SHA");
  const observed = await readCandidateRef(api, auth, branch);
  if (observed.exists) {
    if (observed.sha !== expectedSha) fail("branch_conflict", "Candidate branch already points to a different commit.");
    return { reused: true, ref: observed.ref, sha: expectedSha };
  }
  try {
    const created = await mutationWithReconcile(
      api,
      auth,
      () => invoke(api, "createRef", [`refs/heads/${branch}`, expectedSha]),
      async () => {
        const reconciled = await readCandidateRef(api, auth, branch);
        if (!reconciled.exists) return { completed: false, ambiguous: false };
        if (reconciled.sha !== expectedSha) return { completed: false, ambiguous: true };
        return { completed: true, value: reconciled.ref };
      },
    );
    return { reused: false, ref: created, sha: expectedSha };
  } catch (error) {
    // A provider/network failure can happen after the ref has been written.
    // Reconcile that identity once before surfacing the failure; never issue
    // a blind second createRef request for an unconfirmed outcome.
    try {
      const reconciled = await readCandidateRef(api, auth, branch);
      if (reconciled.exists) {
        if (reconciled.sha !== expectedSha) fail("branch_conflict", "Candidate branch already points to a different commit.");
        return { reused: true, ref: reconciled.ref, sha: expectedSha };
      }
    } catch (reconciliationError) {
      if (reconciliationError instanceof ReleaseAutomationError && reconciliationError.code === "github_api_error" && reconciliationError.details?.status === 404) {
        throw error;
      }
      throw reconciliationError;
    }
    throw error;
  }
}

async function executePhase({ api, auth, artifacts, publisher, context, input, config, preparer, cwd, clock }) {
  const loaded = await loadAndVerifyPreparation({ api, auth, artifacts, state: input.state, input, config, context, clock });
  const identity = authenticatedAppIdentity(auth, loaded.evidence.repository, config.repositoryId ?? loaded.evidence.repositoryId);
  const botLogin = appBotLogin(identity);
  // Runtime decisions (a recorded PR association or merged SHA) are applied
  // after the immutable evidence is validated, so they never alter the digest
  // of the persisted payload.
  let state = { ...loaded.evidence, artifact: loaded.artifact, status: "authorized", ...(input.runtime ?? {}) };
  if (input.runtime?.mergedSha !== undefined) state = { ...state, status: "merged" };
  // Report the completed boundary when the operation-wide deadline expires.
  config.budget?.watch(() => ({
    operationId: state.operationId,
    repository: state.repository,
    attempt: state.attempt,
    status: state.status,
    prNumber: state.prNumber,
    preparedCommitSha: state.preparedCommitSha,
    baseSha: state.baseSha,
    mergedSha: state.mergedSha,
    deadlineAt: new Date(config.budget.deadlineAt).toISOString(),
  }));
  await ensureSameVersionConflict(api, auth, state, config);
  // Reconcile the immutable checkpoint chain with live state before any
  // mutation, so a crash before or after a side effect resumes the recorded
  // identity instead of creating or closing anything a second time.
  const checkpointChain = await discoverCheckpointChain({
    api,
    auth,
    artifacts,
    context,
    version: state.version,
    repository: state.repository,
    repositoryId: state.repositoryId,
    allowedActors: config.allowedActors,
    now: clock.now(),
  });
  const recordedCheckpoints = await reconcileRecordedCheckpoints({ api, auth, chain: checkpointChain, state, botLogin });
  if (recordedCheckpoints.kind === "merged" || recordedCheckpoints.kind === "pr-created") {
    state = {
      ...state,
      branch: branchName(state.operationId, state.version, state.attempt),
      prNumber: recordedCheckpoints.prNumber,
      prHeadSha: state.preparedCommitSha,
      prBaseSha: state.baseSha,
      status: recordedCheckpoints.kind === "merged" ? "merged" : "pr_created",
      ...(recordedCheckpoints.kind === "merged"
        ? { mergedSha: normalizeSha(recordedCheckpoints.mergedSha, "recorded merged SHA") }
        : {}),
    };
  }
  if (state.prNumber === undefined) {
    // Inspect the authoritative protection response before any branch or PR
    // mutation can expose this candidate.
    await validateMainBranchProtection(api, auth, REQUIRED_CHECK_CONTEXTS, {
      repository: state.repository,
      repositoryId: state.repositoryId,
    });
    const main = await apiCall(api, auth, "getRef", ["heads/main"]);
    const currentMain = normalizeSha(main.object?.sha, "current main SHA");
    if (currentMain !== state.baseSha) {
      if (state.attempt >= MAX_CANDIDATE_ATTEMPTS) fail("base_changed_repeatedly", "Candidate attempt budget is exhausted after repeated base changes.");
      fail("base_changed_before_candidate", "Main advanced before candidate exposure; regenerate from current main.", { currentMain });
    }
    await verifyPreparedCommit(api, auth, state);
    const branch = branchName(state.operationId, state.version, state.attempt);
    await exposeCandidateRef(api, auth, branch, state.preparedCommitSha);
    state = { ...state, branch, prHeadSha: state.preparedCommitSha, prBaseSha: state.baseSha };
    // Reconcile before create: an interrupted earlier attempt may already have
    // created the authentic App pull request for this exact candidate. Adopt
    // only a live pull request carrying every expected identity; a conflicting
    // claim on the generated branch stops the operation without closing,
    // editing, labelling or force-pushing it.
    let pr = await findMatchingReleasePullRequest(api, auth, {
      state,
      branch,
      repositoryId: state.repositoryId,
      botLogin,
    });
    if (!pr) {
      pr = await mutationWithReconcile(
        api,
        auth,
        () => invoke(api, "createPullRequest", [{
          title: `chore(release): prepare ${releaseTag(state.version)}`,
          head: branch,
          base: "main",
          body: releaseNotesFromEvidence(state),
          maintainer_can_modify: false,
        }]),
        // The creation request may have succeeded even though its response
        // never arrived. Re-read live pull-request state before concluding
        // that the creation did not happen.
        async () => {
          const existing = await findMatchingReleasePullRequest(api, auth, {
            state,
            branch,
            repositoryId: state.repositoryId,
            botLogin,
          });
          return existing ? { completed: true, value: existing } : { completed: false, ambiguous: false };
        },
      );
      assertPullRequestIdentity(pr, {
        repositoryId: state.repositoryId,
        branch,
        headSha: state.preparedCommitSha,
        baseSha: state.baseSha,
        botLogin,
      });
    }
    const prNumber = normalizePrNumber(pr.number);
    state = { ...state, prNumber, prHeadSha: state.preparedCommitSha, prBaseSha: state.baseSha, status: "pr_created" };
    if (artifacts && typeof artifacts.upload === "function") {
      const checkpoint = await persistImmutableCheckpoint(artifacts, {
        checkpointKind: "pr-created",
        repository: state.repository,
        operationId: state.operationId,
        attempt: state.attempt,
        preparationArtifactId: state.artifact.id,
        preparationArtifactDigest: state.artifact.digest,
        trustedControllerSha: state.trustedControllerSha,
        prNumber,
        prHeadSha: state.prHeadSha,
        prBaseSha: state.prBaseSha,
        ...producerIdentity(context, config),
      }, state);
      state = { ...state, prCheckpoint: checkpoint.artifact };
    }
  } else {
    await verifyPreparedCommit(api, auth, state);
  }
  const gates = await validatePullRequestGates(api, auth, state, { ...config, botLogin });
  if (gates.state === "merged") {
    state = { ...state, mergedSha: normalizeSha(gates.pr.merge_commit_sha, "merged SHA"), status: "merged" };
  } else {
    const checkResult = await waitForPullRequestChecks(api, auth, {
      headSha: state.preparedCommitSha,
      baseSha: state.baseSha,
      requiredContexts: REQUIRED_CHECK_CONTEXTS,
      repository: state.repository,
      repositoryId: state.repositoryId,
      budget: config.budget,
      deadlineMs: config.deadlineMs,
      clock,
    });
    if (checkResult.state !== "passed") fail("checks_not_green", "All seven exact candidate checks must succeed before merge.", checkResult);
    const latestMain = await apiCall(api, auth, "getRef", ["heads/main"]);
    const latestMainSha = normalizeSha(latestMain.object?.sha, "current main SHA");
    if (latestMainSha !== state.baseSha) {
      const refreshed = await apiCall(api, auth, "getPullRequest", [state.prNumber]);
      if (refreshed.merged_at || refreshed.merged === true) {
        state = { ...state, mergedSha: normalizeSha(refreshed.merge_commit_sha, "merged SHA"), status: "merged" };
      } else {
        // The candidate must still be this attempt's own unaltered App pull
        // request. A manual edit stops the operation instead of being closed,
        // overwritten or force-pushed.
        assertPullRequestIdentity(refreshed, {
          repositoryId: state.repositoryId,
          branch: branchName(state.operationId, state.version, state.attempt),
          headSha: state.preparedCommitSha,
          baseSha: state.baseSha,
          botLogin,
          allowStaleBase: true,
        });
        await persistStaleDisposition({
          artifacts,
          evidence: state,
          artifact: state.artifact,
          prNumber: state.prNumber,
          currentMainSha: latestMainSha,
          producer: producerIdentity(context, config),
          recorded: selectAttemptCheckpoints(checkpointChain.records, state.attempt).get("stale-base"),
        });
        await mutationWithReconcile(api, auth, () => invoke(api, "updatePullRequest", [state.prNumber, { state: "closed" }]), async () => {
          const observed = await apiCall(api, auth, "getPullRequest", [state.prNumber]);
          return observed.state === "closed" ? { completed: true, value: observed } : { ambiguous: true };
        });
        if (state.attempt >= MAX_CANDIDATE_ATTEMPTS) {
          fail("base_changed_repeatedly", "Candidate attempt budget is exhausted after repeated base changes.", {
            attempt: state.attempt,
            bound: MAX_CANDIDATE_ATTEMPTS,
            currentMainSha: latestMainSha,
          });
        }
        fail("base_changed", "Candidate was closed as stale; the same version resumes with the next bounded attempt.", {
          attempt: state.attempt,
          nextAttempt: state.attempt + 1,
          currentMainSha: latestMainSha,
          resume: "Dispatch the same canonical version to create the next bounded candidate attempt.",
        });
      }
    } else {
      // Reproduce the entire recorded candidate tree from the recorded base,
      // the requested version and the captured snapshot before the protected
      // merge. The reproduction runs the credential-free preparer in a clean
      // checkout of the recorded base on a path that never holds write
      // credentials, and any difference from the recorded immutable tree stops
      // the merge.
      await reproduceCandidateTree({
        state,
        cwd,
        preparer,
        environment: config.environment ?? process.env,
      });
      // Revalidate the candidate immediately before the protected mutation.
      // Polling can take hours, so the authenticated identity, the open state,
      // resolved discussions and unhandled review requests are re-read here:
      // a head change, newly opened conversation or new review request
      // invalidates every earlier result for this candidate. Re-reading also
      // reconciles a merge that happened while the checks were pending.
      const revalidated = await validatePullRequestGates(api, auth, state, { ...config, botLogin });
      if (revalidated.state === "merged") {
        state = { ...state, mergedSha: normalizeSha(revalidated.pr.merge_commit_sha, "merged SHA"), status: "merged" };
      } else {
        // Re-read protection after all candidate checks and immediately before
        // the protected squash mutation. This closes the settings-drift race
        // without changing or bypassing repository rules.
        await validateMainBranchProtection(api, auth, REQUIRED_CHECK_CONTEXTS, {
          repository: state.repository,
          repositoryId: state.repositoryId,
        });
        const merge = await mutationWithReconcile(
          api,
          auth,
          () => invoke(api, "mergePullRequest", [state.prNumber, { merge_method: "squash", expected_head_sha: state.preparedCommitSha }]),
          async () => {
            const observed = await apiCall(api, auth, "getPullRequest", [state.prNumber]);
            if (observed.merged_at || observed.merged === true) return { completed: true, value: observed };
            if (observed.state !== "open") return { ambiguous: true };
            return { completed: false, ambiguous: false };
          },
        );
        if (merge.merged !== true && !merge.merged_at) fail("merge_rejected", "Protected squash merge was not accepted.");
        state = { ...state, mergedSha: normalizeSha(merge.sha ?? merge.merge_commit_sha, "merged SHA"), status: "merged" };
      }
    }
  }
  const merged = normalizeSha(state.mergedSha, "merged SHA");
  if (artifacts && typeof artifacts.upload === "function" && state.prNumber !== undefined &&
      selectAttemptCheckpoints(checkpointChain.records, state.attempt).get("merged") === undefined) {
    // Record the accepted merged SHA as an immutable checkpoint chained to the
    // preparation artifact so recovery can bind the merge to its intent.
    const mergedCheckpoint = await persistImmutableCheckpoint(artifacts, {
      checkpointKind: "merged",
      repository: state.repository,
      operationId: state.operationId,
      attempt: state.attempt,
      preparationArtifactId: state.artifact.id,
      preparationArtifactDigest: state.artifact.digest,
      trustedControllerSha: state.trustedControllerSha,
      prNumber: state.prNumber,
      prHeadSha: state.preparedCommitSha,
      prBaseSha: state.baseSha,
      mergedSha: merged,
      ...producerIdentity(context, config),
    }, state);
    state = { ...state, mergedCheckpoint: mergedCheckpoint.artifact };
  }
  await verifyCandidateTree(api, auth, merged, state.expectedTree.digest, state.expectedTree.files, state.candidateFiles);
  const mainRef = await apiCall(api, auth, "getRef", ["heads/main"]);
  const mainSha = normalizeSha(mainRef.object?.sha, "main SHA after merge");
  if (mainSha !== merged) {
    // Reachability of the accepted merge commit is a release gate, so a missing
    // comparison primitive fails closed instead of skipping the check.
    if (typeof api.compareCommits !== "function") {
      fail("merged_not_on_main", "Merged commit ancestry cannot be verified without the compare endpoint.", {
        mergedSha: merged,
        mainSha,
      });
    }
    const comparison = await apiCall(api, auth, "compareCommits", [merged, mainSha]);
    if (!["ahead", "identical"].includes(String(comparison.status).toLowerCase())) fail("merged_not_on_main", "Accepted merge commit is not reachable from main.");
  }
  const mainPublication = await pollUntil(
    () => checkMainPublication(api, auth, merged, { repository: state.repository, repositoryId: state.repositoryId }),
    { clock, budget: config.budget, deadlineMs: config.deadlineMs, label: "main and edge verification" },
  );
  if (mainPublication.state !== "passed") fail("main_edge_not_verified", "Main verification and edge publication for the exact merged SHA did not succeed.", mainPublication);
  const tag = releaseTag(state.version);
  const existingTag = await reconcileExistingTag(api, auth, tag, merged);
  const releaseNotes = releaseNotesFromEvidence(state);
  let release = await findReleaseByTag(api, auth, tag);
  if (release) {
    // A draft is intentionally discoverable only through list releases; the
    // tag endpoint returns published releases and cannot recover a draft after
    // a token-expiry or controller restart.
    release = assertReleaseMetadata(release, { tag, mergedSha: merged, notes: releaseNotes, code: "release_conflict" });
  } else {
    if (existingTag.exists) fail("tag_conflict", "Stable tag already exists without an authentic release.");
    release = await mutationWithReconcile(
      api,
      auth,
      () => invoke(api, "createRelease", [{ tag_name: tag, target_commitish: merged, name: `Media Finder ${tag}`, body: releaseNotes, draft: true, prerelease: false }]),
      async () => {
        const observed = await findReleaseByTag(api, auth, tag);
        return observed ? { completed: true, value: observed } : { ambiguous: true };
      },
    );
    release = assertReleaseMetadata(release, { tag, mergedSha: merged, notes: releaseNotes, draft: true, code: "release_readback_mismatch" });
  }
  // Always fetch the provider's complete release DTO before any publish
  // transition. The response from create/update may omit immutable fields.
  let readBack = await readReleaseById(api, auth, release, { tag, mergedSha: merged, notes: releaseNotes });
  const draftTagTarget = await readTagTargetIfPresent(api, auth, tag);
  if (draftTagTarget && draftTagTarget !== merged) fail("tag_conflict", "Draft release tag target does not match the merged commit.");
  if (readBack.draft === true) {
    release = await mutationWithReconcile(
      api,
      auth,
      () => invoke(api, "updateRelease", [release.id, { draft: false }]),
      async () => {
        const observed = await apiCall(api, auth, "getRelease", [release.id]);
        return observed?.draft === false ? { completed: true, value: observed } : { ambiguous: true };
      },
    );
    readBack = await readReleaseById(api, auth, release, { tag, mergedSha: merged, notes: releaseNotes, draft: false });
    const publishedTagTarget = await readTagTargetIfPresent(api, auth, tag);
    if (publishedTagTarget !== merged) fail("tag_conflict", "Published stable release tag does not point to the merged commit.");
    release = readBack;
  } else {
    // A pre-existing published release must have a materialized tag whose
    // peeled target is the exact accepted commit.
    if (draftTagTarget !== merged) fail("tag_conflict", "Published stable release tag does not point to the merged commit.");
    release = readBack;
  }
  state = {
    ...state,
    mergedSha: merged,
    status: "release_published",
    releaseId: Number(release.id),
    releaseUrl: release.html_url,
    mainWorkflowRunId: mainPublication.verification?.id,
    edgeWorkflowRunId: mainPublication.edge?.run_id ?? mainPublication.verification?.id,
    edgeJobId: mainPublication.edge?.id,
  };
  const publication = await waitForPublication(api, auth, artifacts, publisher, state, { clock, budget: config.budget, deadlineMs: config.deadlineMs });
  if (publication.state !== "passed" || !publication.publication) {
    const run = publication.run;
    fail(publication.state === "failed" ? "publication_failed" : "publication_incomplete", "Stable publication did not produce validated canonical evidence; the release remains incomplete.", {
      completedBoundary: state.status,
      releaseId: state.releaseId,
      releaseUrl: state.releaseUrl,
      workflowRunId: run?.id,
      workflowRunAttempt: run?.run_attempt,
      workflowStatus: run?.status,
      workflowConclusion: run?.conclusion,
      publicationState: publication.state,
    });
  }
  state = {
    ...state,
    publication: publication.publication,
    releaseWorkflowRunId: publication.run?.id,
    status: "complete",
  };
  if (config.evidencePath) await writeJsonFile(config.evidencePath, buildStructuredEvidence(state));
  return { state, publication: publication.publication };
}

export const RELEASE_SUMMARY_EVIDENCE_KIND = "release-summary";

const REQUIRED_PUBLICATION_PLATFORMS = Object.freeze(["linux/amd64", "linux/arm64"]);

function safeGithubURL(repository, suffix) {
  if (typeof repository !== "string" || !REPOSITORY_PATTERN.test(repository)) return undefined;
  return `https://github.com/${repository}/${suffix}`;
}

function safeRunURL(repository, runId) {
  const numeric = Number(runId);
  if (!Number.isSafeInteger(numeric) || numeric <= 0) return undefined;
  return safeGithubURL(repository, `actions/runs/${numeric}`);
}

function safePullRequestURL(repository, number) {
  const numeric = Number(number);
  if (!Number.isSafeInteger(numeric) || numeric <= 0) return undefined;
  return safeGithubURL(repository, `pull/${numeric}`);
}

/**
 * Project validated stable-publication evidence into the summary shape. The
 * canonical field is `actualTags`; the projection emits the three tag names
 * plus their full records and never re-emits a `publication` object.
 */
function projectPublication(publication) {
  if (publication === undefined || publication === null) return undefined;
  const value = asObject(publication, "publication evidence");
  const actualTags = Array.isArray(value.actualTags) ? value.actualTags.map((tag) => asObject(tag, "publication tag")) : [];
  const tagNames = actualTags.map((tag) => tag.name).filter((name) => typeof name === "string");
  return {
    state: value.state,
    image: value.image,
    version: value.version,
    releaseTag: value.releaseTag,
    tagNames,
    tagDetails: actualTags,
    digest: value.digest,
    platforms: Array.isArray(value.platforms) ? [...value.platforms] : [],
    sourceRevision: value.sourceRevision,
    workflowURL: value.workflowURL,
    releaseURL: value.releaseURL,
  };
}

/** Completion requires the canonical three-tag, two-platform publication evidence. */
function publicationIsVerified(publication) {
  if (publication === undefined) return false;
  return publication.tagNames.length === 3 &&
    typeof publication.digest === "string" && IMAGE_DIGEST_PATTERN.test(publication.digest) &&
    REQUIRED_PUBLICATION_PLATFORMS.every((platform) => publication.platforms.includes(platform)) &&
    typeof publication.sourceRevision === "string" && SHA_PATTERN.test(publication.sourceRevision);
}

// One authoritative next action per failure code or status. A failure that
// reported an explicit resume instruction (`details.resume`) always wins.
const FAILURE_NEXT_ACTIONS = Object.freeze({
  base_changed: "Re-dispatch the same canonical version from the trusted workflow to obtain the next bounded candidate attempt.",
  base_changed_before_candidate: "Re-dispatch the same canonical version from the trusted workflow to obtain the next bounded candidate attempt.",
  base_changed_repeatedly: "The three-attempt budget is exhausted and a rerun cannot reset it; review the recorded reasons before requesting this version again.",
  operation_deadline_exceeded: "Re-dispatch the same canonical version from the trusted workflow to resume from the immutable recovery state.",
  operation_deadline_invalid: "Fix the requested deadline and re-dispatch the same canonical version.",
  concurrent_release: "Wait for the active release operation to finish, then re-dispatch this version.",
  duplicate_release_state: "Reconcile the existing authenticated release state before re-dispatching this version.",
  checks_not_green: "Re-dispatch the same canonical version after the candidate checks succeed; do not merge without all seven contexts.",
  main_edge_not_verified: "Re-run the guarded main verification and edge publication, then resume the same canonical version.",
  publication_failed: "Re-run the guarded publisher for this release and then resume the same canonical version.",
  publication_incomplete: "Re-run the guarded publisher for this release and then resume the same canonical version.",
  timeout: "Re-dispatch the same canonical version from the trusted workflow to resume from the immutable recovery state.",
});

function releaseNextAction({ status, error } = {}) {
  const explicit = error?.details?.resume;
  if (typeof explicit === "string" && explicit.length > 0 && explicit.length <= 500) return explicit;
  if (error !== undefined && typeof error?.code === "string") {
    return FAILURE_NEXT_ACTIONS[error.code] ?? "Review the safe diagnostic and the recorded completed boundary, then re-dispatch the same canonical version to resume.";
  }
  if (status === "complete") return "No action required.";
  if (status === "incomplete") {
    return "Publication evidence is missing or unverified; re-dispatch the same canonical version and reconcile the stable publication.";
  }
  return "Re-dispatch the same canonical version from the trusted workflow to resume the recorded operation.";
}

/**
 * Canonical, idempotent structured evidence. Passing an already-projected
 * evidence object returns it unchanged, so a second projection can never drop
 * identities. The projection reports success only with verified publication
 * evidence, and it preserves a caller-supplied next action and error block.
 */
export function buildStructuredEvidence(stateOrEvidence) {
  const value = asObject(stateOrEvidence, "release state");
  if (value.evidenceKind === RELEASE_SUMMARY_EVIDENCE_KIND) return value;
  const repository = typeof value.repository === "string" && REPOSITORY_PATTERN.test(value.repository)
    ? value.repository
    : undefined;
  const publication = projectPublication(value.publication);
  const claimsComplete = value.status === "complete";
  const verified = publicationIsVerified(publication);
  const status = claimsComplete && !verified ? "incomplete" : value.status;
  // The projection owns the next action; a caller-supplied string cannot
  // override the per-failure or per-status authority.
  const nextAction = releaseNextAction({ status, error: value.error });
  const prNumber = Number(value.prNumber);
  const pullRequest = Number.isSafeInteger(prNumber) && prNumber > 0
    ? {
      number: prNumber,
      url: typeof value.prUrl === "string" && SAFE_URL_PATTERN.test(value.prUrl)
        ? value.prUrl
        : safePullRequestURL(repository, prNumber),
      headSha: value.prHeadSha ?? value.preparedCommitSha,
      baseSha: value.prBaseSha ?? value.baseSha,
    }
    : undefined;
  const mainRunId = value.mainWorkflowRunId;
  const edgeRunId = value.edgeWorkflowRunId ?? value.mainWorkflowRunId;
  const releaseRunId = value.releaseWorkflowRunId;
  const version = typeof value.version === "string" && VERSION_PATTERN.test(value.version) ? value.version : undefined;
  return {
    schemaVersion: RELEASE_AUTOMATION_SCHEMA_VERSION,
    evidenceKind: RELEASE_SUMMARY_EVIDENCE_KIND,
    operationId: value.operationId,
    status,
    repository,
    attempt: value.attempt,
    baseSha: value.baseSha,
    preparedCommitSha: value.preparedCommitSha,
    pullRequest,
    mergedSha: value.mergedSha,
    release: value.releaseId
      ? {
        id: value.releaseId,
        url: value.releaseUrl,
        tag: version === undefined ? undefined : releaseTag(version),
      }
      : undefined,
    tagNames: publication?.tagNames,
    tagDetails: publication?.tagDetails,
    digest: publication?.digest,
    platforms: publication?.platforms,
    sourceRevision: publication?.sourceRevision,
    image: publication?.image,
    releaseTag: publication?.releaseTag,
    publicationState: publication?.state,
    workflow: {
      requestRunId: value.originRunId,
      requestRunURL: safeRunURL(repository, value.originRunId),
      mainRunId,
      mainRunURL: safeRunURL(repository, mainRunId),
      edgeRunId,
      edgeRunURL: safeRunURL(repository, edgeRunId),
      edgeJobId: value.edgeJobId,
      releaseRunId,
      releaseRunURL: safeRunURL(repository, releaseRunId),
    },
    nextAction,
    ...(value.error === undefined ? {} : { error: value.error }),
  };
}

/**
 * Canonical blocked evidence for a failed or timed-out controller run. It
 * carries the completed boundary when the failure reported one, its own next
 * action and the safe error block, so the workflow summary never replaces them
 * with a generic resume message.
 */
export function buildBlockedEvidence({ error, environment = process.env } = {}) {
  const failure = error instanceof ReleaseAutomationError
    ? error
    : new ReleaseAutomationError("controller_failed", "Release controller failed safely.");
  const candidate = failure.details?.completedBoundary;
  const boundary = candidate !== null && typeof candidate === "object" && !Array.isArray(candidate) ? candidate : undefined;
  const projected = buildStructuredEvidence({
    operationId: boundary?.operationId ?? environment.RELEASE_OPERATION_ID,
    repository: boundary?.repository,
    attempt: boundary?.attempt,
    status: "blocked",
    prNumber: boundary?.prNumber,
    prHeadSha: boundary?.preparedCommitSha,
    baseSha: boundary?.baseSha,
    preparedCommitSha: boundary?.preparedCommitSha,
    mergedSha: boundary?.mergedSha,
    error: { code: failure.code, message: failure.message, details: failure.details },
  });
  return {
    ...projected,
    status: "blocked",
  };
}

export function formatWorkflowSummary(stateOrEvidence) {
  // The projection is idempotent, so already-projected evidence passes through
  // unchanged and no identity can be lost by a second projection.
  const evidence = buildStructuredEvidence(stateOrEvidence);
  const workflow = evidence.workflow ?? {};
  const lines = [
    `## Stable release ${evidence.status ?? "unknown"}`,
    "",
    `- Operation: \`${evidence.operationId ?? "unknown"}\``,
    `- Repository: ${evidence.repository ?? "unknown"} (attempt ${evidence.attempt ?? "unknown"})`,
    `- Pull request: ${evidence.pullRequest?.url ?? "not created"}`,
    `- Head/base: \`${evidence.pullRequest?.headSha ?? "unknown"}\` / \`${evidence.pullRequest?.baseSha ?? "unknown"}\``,
    `- Merged SHA: \`${evidence.mergedSha ?? "not merged"}\``,
    `- Release: ${evidence.release?.url ?? "not created"}`,
    `- Main/edge workflow runs: ${workflow.mainRunId ?? "unknown"} / ${workflow.edgeRunId ?? "unknown"}`,
    `- Release workflow run: ${workflow.releaseRunId ?? "unknown"}`,
    `- Workflow URLs: ${workflow.mainRunURL ?? "unavailable"} / ${workflow.releaseRunURL ?? "unavailable"}`,
    `- Tags: ${(evidence.tagNames ?? []).join(", ") || "not verified"}`,
    `- Digest: \`${evidence.digest ?? "not verified"}\``,
    `- Platforms: ${(evidence.platforms ?? []).join(", ") || "not verified"}`,
    `- Source revision: \`${evidence.sourceRevision ?? "not verified"}\``,
    `- Next action: ${evidence.nextAction ?? "Review the recorded boundary before resuming."}`,
  ];
  if (evidence.error !== undefined) {
    lines.push(`- Failure: \`${evidence.error.code ?? "unknown"}\` ${evidence.error.message ?? ""}`.trimEnd());
  }
  lines.push("", "Machine-readable evidence:", "", "```json", canonicalJson(evidence), "```");
  return lines.join("\n");
}

async function writeSummary(summary, environment = process.env) {
  if (!environment.GITHUB_STEP_SUMMARY) return;
  await fsp.appendFile(environment.GITHUB_STEP_SUMMARY, `${summary}\n`, "utf8");
}

/**
 * The single production entry point invoked by the main-only preparation
 * workflow (`--phase request --version <version>`).
 *
 * It composes the documented flow rather than replacing it: an authenticated
 * same-version preparation is resumed, otherwise preparation runs first, and
 * the operation then continues through candidate checks, the protected squash
 * merge and publication. A re-dispatch with the same canonical version is the
 * documented resume path, so duplicate authenticated state is reconciled
 * instead of rejected.
 */
async function requestPhase({ api, auth, artifacts, publisher, context, input, config, preparer, cwd, clock }) {
  const requestedVersion = parseStableVersion(input.version, "requested version").text;
  const repository = config.repository ?? context.repository;
  let state = input.state;
  let resolvedRuntime;
  if (!state) {
    const resolved = await resolveReleaseRequest({
      api,
      auth,
      artifacts,
      context,
      version: requestedVersion,
      repository,
      repositoryId: config.repositoryId,
      allowedActors: config.allowedActors,
      now: clock.now(),
      botLogin: appBotLogin(authenticatedAppIdentity(auth, repository, config.repositoryId)),
      producer: producerIdentity(context, config),
    });
    if (resolved.kind === "resume") {
      state = resolved.state;
      resolvedRuntime = resolved.runtime;
    } else {
      // A fresh request prepares attempt 1. A replacement prepares the next
      // bounded attempt from current main and re-captures the release-note
      // inputs from that base instead of reusing the stale snapshot.
      const prepared = await preparePhase({
        api,
        auth,
        artifacts,
        context,
        input: {
          ...input,
          version: requestedVersion,
          attempt: resolved.attempt ?? 1,
          ...(resolved.operationId === undefined ? {} : { operationId: resolved.operationId }),
          notesInputSnapshot: undefined,
        },
        config,
        preparer,
        cwd,
      });
      state = prepared.state;
    }
  }
  return await executePhase({
    api,
    auth,
    artifacts,
    publisher,
    context,
    input: { ...input, state, ...(resolvedRuntime === undefined ? {} : { runtime: resolvedRuntime }) },
    config,
    preparer,
    cwd,
    clock,
  });
}

export async function runReleaseAutomation({
  phase = "execute",
  api,
  auth,
  artifacts,
  publisher,
  preparer,
  context,
  input = {},
  config = {},
  cwd = process.cwd(),
  clock = normalizeClock(),
} = {}) {
  const environment = config.environment ?? process.env;
  const actualContext = context ?? defaultContext(environment);
  const configuredAllowedActors = config.allowedActors ?? String(environment.RELEASE_ALLOWED_ACTORS ?? "").split(",").map((item) => item.trim()).filter(Boolean);
  const trustedControllerSha = config.trustedControllerSha ?? environment.GITHUB_SHA;
  // Every privileged phase, including resume, must originate from the trusted
  // main-branch dispatch context. Validate it before issuing or using a token
  // and before reading mutable recovery state.
  validateDispatchContext(actualContext, {
    repository: actualContext.repository,
    allowedActors: configuredAllowedActors,
    trustedControllerSha,
  });
  const repository = normalizeRepository(actualContext.repository);
  const actualAuth = auth ?? await defaultAuthenticator(environment, repository);
  if (!api) {
    await ensureApiAuth(actualAuth);
    api = new GitHubRestApi({ auth: actualAuth, repository });
  }
  await ensureApiAuth(actualAuth);
  await validateInitiatingActor(api, actualAuth, actualContext.actor);
  const statePaths = [input.statePath, config.statePath].filter((value, index, values) => value && values.indexOf(value) === index);
  let recoveredState = input.state;
  if (!recoveredState && ["execute", "resume"].includes(phase)) {
    for (const statePath of statePaths) {
      try {
        const raw = await fsp.readFile(statePath, "utf8");
        try {
          recoveredState = JSON.parse(raw);
        } catch {
          fail("preparation_state_invalid", "Persisted preparation state is not valid JSON.");
        }
        break;
      } catch (error) {
        if (error?.code === "ENOENT") continue;
        fail("preparation_state_unavailable", "Persisted preparation state could not be read.");
      }
    }
  }
  const actualConfig = {
    ...config,
    environment,
    repository,
    appId: config.appId ?? environment.RELEASE_APP_ID ?? environment.RELEASE_APP_CLIENT_ID ?? actualAuth.current?.identity?.appId,
    installationId: config.installationId ?? environment.RELEASE_APP_INSTALLATION_ID ?? actualAuth.current?.identity?.installationId,
    repositoryId: config.repositoryId ?? environment.RELEASE_REPOSITORY_ID ?? actualAuth.current?.identity?.repositoryId,
    allowedActors: configuredAllowedActors,
    trustedControllerSha,
    statePath: config.statePath,
    evidencePath: config.evidencePath ?? path.join(cwd, ".release-automation", "evidence.json"),
  };
  // Assign the single operation-wide deadline once, before any privileged work,
  // so every bounded wait shares the same budget instead of defaulting per poll.
  if (actualConfig.budget === undefined) {
    actualConfig.budget = createOperationBudget({
      clock: normalizeClock(clock),
      deadlineMs: config.operationDeadlineMs ?? DEFAULT_OPERATION_DEADLINE_MS,
    });
  }
  if (["execute", "resume", "request"].includes(phase)) {
    // Recovery is a privileged read as well as a write. Require the current
    // installation's complete App identity before accepting explicit state or
    // discovering an artifact from workflow history.
    authenticatedAppIdentity(actualAuth, repository, actualConfig.repositoryId);
  }
  // The maintained Actions SDK is the only production artifact transport. A
  // later workflow attempt discovers the original run from immutable state so
  // its download is scoped to that run rather than the current run's name.
  if (!artifacts) {
    // Uploads (preparation evidence and checkpoints) are produced by this
    // executing run; every download names the artifact's producing run.
    artifacts = await createActionsArtifactStore({
      repository,
      workflowRunId: actualContext.runId,
      tokenProvider: async () => (await actualAuth.ensureToken()).token,
      metadataReader: async (artifactId) => apiCall(api, actualAuth, "getArtifact", [artifactId]),
      temporaryDirectory: path.join(os.tmpdir(), "media-finder-release-artifacts"),
    });
  }
  actualConfig.artifactWriter = artifacts;
  let result;
  if (phase === "prepare") {
    // Reusing an authenticated preparation is safe only after discovery has
    // proved its immutable artifact and origin. Run this check before the
    // normal version/base validation so a duplicate prepare cannot mint a
    // second candidate for an already prepared version.
    const existing = await discoverPreparationEvidence({
      api,
      auth: actualAuth,
      artifacts,
      context: actualContext,
      version: input.version,
      repository,
      repositoryId: actualConfig.repositoryId,
      allowedActors: configuredAllowedActors,
      now: normalizeClock(clock).now(),
    });
    if (existing) {
      fail("duplicate_release_state", "An authenticated preparation already exists for the requested version.", {
        operationId: existing.evidence.operationId,
        attempt: existing.evidence.attempt,
      });
    }
    result = await preparePhase({ api, auth: actualAuth, artifacts, context: actualContext, input, config: actualConfig, preparer, cwd });
  } else if (["execute", "resume"].includes(phase)) {
    let state = recoveredState;
    if (!state) {
      const discovered = await discoverPreparationEvidence({
        api,
        auth: actualAuth,
        artifacts,
        context: actualContext,
        version: input.version,
        repository,
        repositoryId: actualConfig.repositoryId,
        allowedActors: configuredAllowedActors,
        now: normalizeClock(clock).now(),
      });
      if (!discovered) fail("preparation_artifact_missing", "No authenticated preparation artifact was found for the requested version.");
      state = discovered.state;
    }
    result = await executePhase({ api, auth: actualAuth, artifacts, publisher, context: actualContext, input: { ...input, state }, config: actualConfig, preparer, cwd, clock: normalizeClock(clock) });
  } else if (phase === "request") {
    result = await requestPhase({ api, auth: actualAuth, artifacts, publisher, context: actualContext, input, config: actualConfig, preparer, cwd, clock: normalizeClock(clock) });
  } else {
    fail("phase_invalid", "Release automation phase is unsupported.");
  }
  const evidence = buildStructuredEvidence(result.state);
  await writeSummary(formatWorkflowSummary(evidence), environment);
  return { ...result, evidence };
}

function parseCliArguments(arguments_) {
  const parsed = {};
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index];
    if (!argument.startsWith("--")) fail("unsafe_input", "Release controller arguments must use named options.");
    const key = argument.slice(2).replaceAll("-", "_");
    const value = arguments_[index + 1];
    if (!value || value.startsWith("--")) fail("unsafe_input", `Missing value for --${key}.`);
    parsed[key] = value;
    index += 1;
  }
  return parsed;
}

async function cli() {
  try {
    const args = parseCliArguments(process.argv.slice(2));
    const environment = process.env;
    const phase = args.phase ?? "execute";
    const statePath = args.state ?? args.state_path ?? path.join(process.cwd(), ".release-automation", "preparation.json");
    const input = {
      version: args.version ?? environment.RELEASE_VERSION,
      artifactId: args.artifact_id ?? environment.PREPARATION_ARTIFACT_ID,
      artifactDigest: args.artifact_digest ?? environment.PREPARATION_ARTIFACT_DIGEST,
      statePath,
      currentVersion: environment.RELEASE_CURRENT_VERSION,
    };
    if (["prepare", "request"].includes(phase) && !input.version) fail("invalid_version", "workflow_dispatch version input is required.");
    const result = await runReleaseAutomation({ phase, input, config: { statePath, environment, evidencePath: environment.RELEASE_EVIDENCE_PATH } });
    process.stdout.write(`${canonicalJson(result.evidence)}\n`);
  } catch (error) {
    const failure = error instanceof ReleaseAutomationError
      ? error
      : new ReleaseAutomationError("controller_failed", "Release controller failed safely.");
    const evidence = buildBlockedEvidence({ error: failure, environment: process.env });
    try {
      await writeSummary(formatWorkflowSummary(evidence), process.env);
      if (process.env.RELEASE_EVIDENCE_PATH) await writeJsonFile(process.env.RELEASE_EVIDENCE_PATH, evidence);
    } catch {
      // Keep the original safe failure as the CLI result.
    }
    console.error(`${failure.code}: ${failure.message}`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  await cli();
}
