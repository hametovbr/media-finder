import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import YAML from "yaml";

const MANIFEST_PATH = ".github/security-exceptions.yaml";
const REPOSITORY_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const EXCEPTION_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const GH_TIMEOUT_MILLISECONDS = 30_000;
const REPOSITORY_SECURITY_STATUSES = new Set(["enabled", "disabled"]);
const HOSTED_ALERT_PATTERN =
  /^https:\/\/github\.com\/(?<owner>[A-Za-z0-9_.-]+)\/(?<repository>[A-Za-z0-9_.-]+)\/security\/code-scanning\/(?<number>[1-9]\d*)$/;

function parseRepositoryArgument(arguments_) {
  const normalizedArguments = arguments_[0] === "--" ? arguments_.slice(1) : arguments_;
  if (
    normalizedArguments.length !== 2 ||
    normalizedArguments[0] !== "--repository" ||
    !REPOSITORY_PATTERN.test(normalizedArguments[1])
  ) {
    return undefined;
  }
  return normalizedArguments[1];
}

function readJsonFromGh(endpoint) {
  const result = spawnSync("gh", ["api", "--hostname", "github.com", endpoint], {
    encoding: "utf8",
    maxBuffer: 1024 * 1024,
    shell: false,
    timeout: GH_TIMEOUT_MILLISECONDS,
  });
  if (result.error || result.status !== 0) return { state: "unavailable" };
  try {
    return { state: "available", value: JSON.parse(result.stdout) };
  } catch {
    return { state: "malformed" };
  }
}

function hasSecurityExceptionMarker(content, identifier) {
  return (
    typeof content === "string" &&
    EXCEPTION_ID_PATTERN.test(identifier) &&
    new RegExp(`security-exception: ${identifier}(?![a-z0-9-])`).test(content)
  );
}

function readHostedExceptions(root) {
  try {
    const manifest = YAML.parse(fs.readFileSync(path.join(root, MANIFEST_PATH), "utf8"));
    if (manifest?.schema_version !== 1 || !Array.isArray(manifest.exceptions)) {
      return undefined;
    }
    const hostedExceptions = manifest.exceptions.filter(
      (exception) => exception?.suppression?.kind === "github-code-scanning-alert",
    );
    if (
      hostedExceptions.some(
        (exception) =>
          typeof exception?.id !== "string" ||
          exception.id.length > 100 ||
          !EXCEPTION_ID_PATTERN.test(exception.id),
      )
    ) {
      return undefined;
    }
    return hostedExceptions;
  } catch {
    return undefined;
  }
}

function fail(message, status = 1) {
  console.error(message);
  process.exitCode = status;
}

function verify() {
  const repository = parseRepositoryArgument(process.argv.slice(2));
  if (!repository) {
    fail("Usage: pnpm security:verify -- --repository OWNER/REPO");
    return;
  }

  const repositoryResult = readJsonFromGh(`repos/${repository}`);
  if (repositoryResult.state === "unavailable") {
    fail(`Unable to read repository security settings for ${repository}.`, 2);
    return;
  }
  if (repositoryResult.state === "malformed") {
    fail(`Malformed repository security settings for ${repository}.`);
    return;
  }

  const response = repositoryResult.value;
  if (response === null || typeof response !== "object" || Array.isArray(response)) {
    fail(`Malformed repository security settings for ${repository}.`);
    return;
  }
  if (typeof response?.full_name !== "string" || response.full_name.toLowerCase() !== repository.toLowerCase()) {
    fail(`Repository identity does not match ${repository}.`);
    return;
  }
  const secretScanning = response?.security_and_analysis?.secret_scanning?.status;
  const pushProtection = response?.security_and_analysis?.secret_scanning_push_protection?.status;
  if (
    !REPOSITORY_SECURITY_STATUSES.has(secretScanning) ||
    !REPOSITORY_SECURITY_STATUSES.has(pushProtection)
  ) {
    fail(`Malformed repository security settings for ${repository}.`);
    return;
  }
  if (secretScanning !== "enabled" || pushProtection !== "enabled") {
    if (secretScanning !== "enabled") {
      console.error(`Repository ${repository} secret scanning: disabled.`);
    }
    if (pushProtection !== "enabled") {
      console.error(`Repository ${repository} push protection: disabled.`);
    }
    process.exitCode = 1;
    return;
  }

  const hostedExceptions = readHostedExceptions(process.cwd());
  if (!hostedExceptions) {
    fail(`Malformed or missing ${MANIFEST_PATH}.`);
    return;
  }

  const verified = [];
  for (const exception of hostedExceptions) {
    const identifier =
      typeof exception?.id === "string" && exception.id ? exception.id : "unidentified-exception";
    const match =
      typeof exception?.suppression?.url === "string"
        ? exception.suppression.url.match(HOSTED_ALERT_PATTERN)
        : undefined;
    if (
      !match ||
      `${match.groups.owner}/${match.groups.repository}`.toLowerCase() !== repository.toLowerCase()
    ) {
      fail(`${identifier}: hosted alert does not belong to ${repository}.`);
      return;
    }

    const endpoint = `repos/${repository}/code-scanning/alerts/${match.groups.number}`;
    const alertResult = readJsonFromGh(endpoint);
    if (alertResult.state === "unavailable") {
      fail(`Unable to read hosted exception ${identifier}.`, 2);
      return;
    }
    if (
      alertResult.state === "malformed" ||
      alertResult.value === null ||
      typeof alertResult.value !== "object" ||
      Array.isArray(alertResult.value)
    ) {
      fail(`${identifier}: hosted alert evidence is malformed.`);
      return;
    }
    if (alertResult.value.state !== "dismissed") {
      fail(`${identifier}: hosted alert is not dismissed.`);
      return;
    }
    if (
      typeof alertResult.value.dismissed_comment !== "string" ||
      !hasSecurityExceptionMarker(alertResult.value.dismissed_comment, identifier)
    ) {
      fail(`${identifier}: dismissal marker is missing.`);
      return;
    }
    verified.push(identifier);
  }

  console.log(
    `Repository security verified: ${repository} (secret scanning: enabled, push protection: enabled).`,
  );
  for (const identifier of verified) {
    console.log(`Hosted security exception verified: ${identifier}.`);
  }
}

verify();
