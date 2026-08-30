import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import YAML from "yaml";

const sourceRoot = path.resolve(import.meta.dirname, "..");
const verifierPath = path.join(sourceRoot, "scripts/verify-repository-security.mjs");
const repository = "hametovbr/media-finder";
const repositoryEndpoint = `repos/${repository}`;
const alertEndpoint = `repos/${repository}/code-scanning/alerts/123`;
const hostedExceptionId = "security-exception-codeql-example";

function repositoryResponse(secretScanning = "enabled", pushProtection = "enabled") {
  return {
    full_name: repository,
    security_and_analysis: {
      secret_scanning: { status: secretScanning },
      secret_scanning_push_protection: { status: pushProtection },
    },
    private_payload: "must-not-be-emitted",
  };
}

function hostedException(overrides = {}) {
  const alertUrl = `https://github.com/${repository}/security/code-scanning/123`;
  return {
    id: hostedExceptionId,
    scanner: "codeql",
    finding_id: "js/example-query",
    severity: "medium",
    scope: "packages/builtin-ui/src/example.ts:10",
    disposition: "false-positive",
    rationale: "The bounded fixture is unreachable in production.",
    owner: "@maintainer",
    tracking_ref: alertUrl,
    approved_on: "2026-08-01",
    expires_on: "2026-10-01",
    suppression: {
      kind: "github-code-scanning-alert",
      url: alertUrl,
    },
    ...overrides,
  };
}

function writeManifest(root, exceptions = []) {
  const target = path.join(root, ".github/security-exceptions.yaml");
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(
    target,
    YAML.stringify({ schema_version: 1, exceptions }),
    "utf8",
  );
}

function writeFakeGh(root) {
  const bin = path.join(root, "bin");
  fs.mkdirSync(bin, { recursive: true });
  const target = path.join(bin, "gh");
  fs.writeFileSync(
    target,
    `#!/usr/bin/env node
const args = process.argv.slice(2);
const hasPinnedHost =
  args.length === 4 &&
  args[0] === "api" &&
  args[1] === "--hostname" &&
  args[2] === "github.com";
if (process.env.TEST_GH_REQUIRE_PINNED_HOST === "1" && !hasPinnedHost) {
  process.stderr.write("authoritative host was not pinned\\n");
  process.exit(1);
}
const endpoint = hasPinnedHost ? args[3] : args[1];
const errors = new Set(JSON.parse(process.env.TEST_GH_ERRORS ?? "[]"));
if (errors.has(endpoint)) {
  process.stderr.write("upstream private diagnostic must-not-be-emitted\\n");
  process.exit(1);
}
const hangs = new Set(JSON.parse(process.env.TEST_GH_HANGS ?? "[]"));
if (hangs.has(endpoint)) {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 31000);
}
const responses = JSON.parse(process.env.TEST_GH_RESPONSES ?? "{}");
if (!Object.hasOwn(responses, endpoint)) {
  process.stderr.write("unexpected endpoint must-not-be-emitted\\n");
  process.exit(1);
}
process.stdout.write(JSON.stringify(responses[endpoint]));
`,
    { encoding: "utf8", mode: 0o755 },
  );
  return bin;
}

function runVerifier({
  responses,
  errors = [],
  hangs = [],
  exceptions = [],
  selectedRepository = repository,
  pnpmSeparator = false,
  ghHost,
  requirePinnedHost = false,
}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "media-finder-security-verifier-"));
  writeManifest(root, exceptions);
  const bin = writeFakeGh(root);
  const result = spawnSync(
    process.execPath,
    [verifierPath, ...(pnpmSeparator ? ["--"] : []), "--repository", selectedRepository],
    {
      cwd: root,
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}`,
        TEST_GH_ERRORS: JSON.stringify(errors),
        TEST_GH_HANGS: JSON.stringify(hangs),
        TEST_GH_RESPONSES: JSON.stringify(responses),
        TEST_GH_REQUIRE_PINNED_HOST: requirePinnedHost ? "1" : "0",
        ...(ghHost ? { GH_HOST: ghHost } : {}),
      },
    },
  );
  fs.rmSync(root, { recursive: true, force: true });
  return result;
}

test("enabled repository secret scanning and push protection pass", () => {
  const result = runVerifier({
    responses: { [repositoryEndpoint]: repositoryResponse() },
  });

  assert.equal(
    result.status,
    0,
    JSON.stringify({ stdout: result.stdout, stderr: result.stderr, error: result.error?.message }),
  );
  assert.match(result.stdout, /hametovbr\/media-finder/);
  assert.match(result.stdout, /secret scanning: enabled/);
  assert.match(result.stdout, /push protection: enabled/);
  assert.equal(result.stderr, "");
  assert.doesNotMatch(result.stdout, /must-not-be-emitted/);
});

test("the documented pnpm separator form verifies repository security", () => {
  const result = runVerifier({
    responses: { [repositoryEndpoint]: repositoryResponse() },
    pnpmSeparator: true,
  });

  assert.equal(result.status, 0);
  assert.match(result.stdout, /Repository security verified/);
});

test("authoritative queries pin the complete github.com argument array", () => {
  const result = runVerifier({
    responses: { [repositoryEndpoint]: repositoryResponse() },
    ghHost: "example.invalid",
    requirePinnedHost: true,
  });

  assert.equal(result.status, 0);
  assert.match(result.stdout, /Repository security verified/);
  assert.doesNotMatch(result.stderr, /authoritative host was not pinned/);
});

test("a timed-out authoritative query is blocked without subprocess diagnostics", () => {
  const result = runVerifier({
    responses: { [repositoryEndpoint]: repositoryResponse() },
    hangs: [repositoryEndpoint],
  });

  assert.equal(result.status, 2);
  assert.match(result.stderr, /Unable to read repository security settings/);
  assert.doesNotMatch(`${result.stdout}${result.stderr}`, /must-not-be-emitted|ETIMEDOUT/);
});

for (const [label, secretScanning, pushProtection] of [
  ["secret scanning", "disabled", "enabled"],
  ["push protection", "enabled", "disabled"],
]) {
  test(`disabled ${label} fails with safe state only`, () => {
    const result = runVerifier({
      responses: {
        [repositoryEndpoint]: repositoryResponse(secretScanning, pushProtection),
      },
    });

    assert.equal(result.status, 1);
    assert.match(result.stderr, new RegExp(`${label}.*disabled`));
    assert.doesNotMatch(`${result.stdout}${result.stderr}`, /must-not-be-emitted/);
  });
}

test("unauthorized repository evidence is blocked without relaying upstream diagnostics", () => {
  const result = runVerifier({
    responses: {},
    errors: [repositoryEndpoint],
  });

  assert.equal(result.status, 2);
  assert.match(result.stderr, /Unable to read repository security settings for hametovbr\/media-finder/);
  assert.doesNotMatch(result.stderr, /must-not-be-emitted|upstream private diagnostic/);
});

test("malformed repository evidence fails without emitting the raw payload", () => {
  const result = runVerifier({
    responses: {
      [repositoryEndpoint]: {
        full_name: repository,
        security_and_analysis: {},
        private_payload: "must-not-be-emitted",
      },
    },
  });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /Malformed repository security settings for hametovbr\/media-finder/);
  assert.doesNotMatch(result.stderr, /must-not-be-emitted/);
});

for (const [label, response] of [
  ["null", null],
  ["array", []],
]) {
  test(`${label} repository evidence fails as malformed without a stack trace`, () => {
    const result = runVerifier({ responses: { [repositoryEndpoint]: response } });

    assert.equal(result.status, 1);
    assert.match(result.stderr, /Malformed repository security settings/);
    assert.doesNotMatch(result.stderr, /TypeError|Cannot read/);
  });
}

test("unexpected repository status fails without emitting the raw value", () => {
  const result = runVerifier({
    responses: {
      [repositoryEndpoint]: repositoryResponse("must-not-be-emitted", "enabled"),
    },
  });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /Malformed repository security settings/);
  assert.doesNotMatch(result.stderr, /must-not-be-emitted/);
});

test("repository identity must match the requested target", () => {
  const result = runVerifier({
    responses: {
      [repositoryEndpoint]: {
        ...repositoryResponse(),
        full_name: "different/repository",
      },
    },
  });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /Repository identity does not match hametovbr\/media-finder/);
  assert.doesNotMatch(result.stderr, /different\/repository/);
});

test("a matching dismissed GitHub-hosted exception passes without alert details", () => {
  const result = runVerifier({
    exceptions: [hostedException()],
    responses: {
      [repositoryEndpoint]: repositoryResponse(),
      [alertEndpoint]: {
        number: 123,
        state: "dismissed",
        dismissed_comment: `Reviewed under security-exception: ${hostedExceptionId}`,
        rule: { id: "js/example-query", description: "must-not-be-emitted" },
        most_recent_instance: { location: { path: "must-not-be-emitted" } },
      },
    },
  });

  assert.equal(result.status, 0);
  assert.match(result.stdout, new RegExp(hostedExceptionId));
  assert.doesNotMatch(`${result.stdout}${result.stderr}`, /js\/example-query|must-not-be-emitted/);
});

test("a hosted dismissal marker does not accept an identifier prefix", () => {
  const identifier = "a";
  const result = runVerifier({
    exceptions: [hostedException({ id: identifier })],
    responses: {
      [repositoryEndpoint]: repositoryResponse(),
      [alertEndpoint]: {
        number: 123,
        state: "dismissed",
        dismissed_comment: "Reviewed under security-exception: a-longer",
      },
    },
  });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /a: dismissal marker is missing/);
});

for (const [label, response] of [
  ["null", null],
  ["array", []],
]) {
  test(`${label} hosted evidence fails as malformed without a stack trace`, () => {
    const result = runVerifier({
      exceptions: [hostedException()],
      responses: {
        [repositoryEndpoint]: repositoryResponse(),
        [alertEndpoint]: response,
      },
    });

    assert.equal(result.status, 1);
    assert.match(result.stderr, new RegExp(`${hostedExceptionId}.*evidence is malformed`));
    assert.doesNotMatch(result.stderr, /TypeError|Cannot read/);
  });
}

test("a malformed hosted exception identifier is never emitted", () => {
  const result = runVerifier({
    exceptions: [hostedException({ id: "MUST-NOT-BE-EMITTED" })],
    responses: {
      [repositoryEndpoint]: repositoryResponse(),
      [alertEndpoint]: {
        number: 123,
        state: "dismissed",
        dismissed_comment: "Reviewed under MUST-NOT-BE-EMITTED",
      },
    },
  });

  assert.equal(result.status, 1);
  assert.match(result.stderr, /Malformed or missing \.github\/security-exceptions\.yaml/);
  assert.doesNotMatch(`${result.stdout}${result.stderr}`, /MUST-NOT-BE-EMITTED/);
});

test("a GitHub-hosted dismissal without its exception marker fails safely", () => {
  const result = runVerifier({
    exceptions: [hostedException()],
    responses: {
      [repositoryEndpoint]: repositoryResponse(),
      [alertEndpoint]: {
        number: 123,
        state: "dismissed",
        dismissed_comment: "Reviewed without the required marker",
        rule: { id: "must-not-be-emitted" },
      },
    },
  });

  assert.equal(result.status, 1);
  assert.match(result.stderr, new RegExp(`${hostedExceptionId}.*dismissal marker`));
  assert.doesNotMatch(result.stderr, /Reviewed without|must-not-be-emitted/);
});

test("an unavailable GitHub-hosted alert is blocked without upstream diagnostics", () => {
  const result = runVerifier({
    exceptions: [hostedException()],
    responses: { [repositoryEndpoint]: repositoryResponse() },
    errors: [alertEndpoint],
  });

  assert.equal(result.status, 2);
  assert.match(result.stderr, new RegExp(`Unable to read hosted exception ${hostedExceptionId}`));
  assert.doesNotMatch(result.stderr, /must-not-be-emitted|upstream private diagnostic/);
});
