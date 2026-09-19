import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { parse as parseToml } from "smol-toml";
import YAML from "yaml";

function requireValue(failures, condition, message) {
  if (!condition) failures.push(message);
}

function readText(root, relativePath, failures) {
  const target = path.join(root, relativePath);
  if (!fs.existsSync(target)) {
    failures.push(`${relativePath}: required delivery artifact is missing`);
    return "";
  }
  return fs.readFileSync(target, "utf8");
}

function loadYaml(root, relativePath, failures) {
  const content = readText(root, relativePath, failures);
  if (!content) return {};
  try {
    return YAML.parse(content) ?? {};
  } catch {
    failures.push(`${relativePath}: invalid YAML`);
    return {};
  }
}

const SECURITY_EXCEPTION_MANIFEST = ".github/security-exceptions.yaml";
const SECURITY_EXCEPTION_SEVERITIES = new Set([
  "critical",
  "high",
  "medium",
  "low",
  "unknown",
]);
const SECURITY_EXCEPTION_DISPOSITIONS = new Set([
  "false-positive",
  "accepted-risk",
  "temporary-mitigation",
]);
const SECURITY_EXCEPTION_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SECURITY_EXCEPTION_MAX_TEXT = 2048;
const DAY_IN_MILLISECONDS = 24 * 60 * 60 * 1000;

function exactUtcDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return undefined;
  const milliseconds = Date.parse(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(milliseconds)) return undefined;
  return new Date(milliseconds).toISOString().slice(0, 10) === value
    ? milliseconds
    : undefined;
}

function safeTrackingReference(value) {
  if (typeof value !== "string") return false;
  return (
    /^#[1-9]\d*$/.test(value) ||
    /^GHSA-[A-Za-z0-9-]+$/.test(value) ||
    /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/(?:issues\/[1-9]\d*|security\/(?:advisories\/GHSA-[A-Za-z0-9-]+|code-scanning\/[1-9]\d*))$/.test(
      value,
    )
  );
}

function exceptionLabel(exception, index) {
  return typeof exception?.id === "string" &&
    exception.id.length <= 100 &&
    SECURITY_EXCEPTION_ID_PATTERN.test(exception.id)
    ? exception.id
    : `exception[${index}]`;
}

function hasSecurityExceptionMarker(content, identifier) {
  return (
    typeof content === "string" &&
    typeof identifier === "string" &&
    identifier.length <= 100 &&
    SECURITY_EXCEPTION_ID_PATTERN.test(identifier) &&
    new RegExp(`security-exception: ${identifier}(?![a-z0-9-])`).test(content)
  );
}

function validRequiredText(exception, field, label, failures) {
  const value = exception?.[field];
  const valid =
    typeof value === "string" &&
    value.trim().length > 0 &&
    value.length <= SECURITY_EXCEPTION_MAX_TEXT;
  requireValue(
    failures,
    valid,
    `${SECURITY_EXCEPTION_MANIFEST}: ${label} ${field} must be non-empty and at most ${SECURITY_EXCEPTION_MAX_TEXT} characters`,
  );
  return valid;
}

function safeRepositoryPath(relativePath) {
  if (typeof relativePath !== "string" || !relativePath.trim() || path.isAbsolute(relativePath)) {
    return false;
  }
  const normalized = path.normalize(relativePath);
  return normalized !== "." && normalized !== ".." && !normalized.startsWith(`..${path.sep}`);
}

function validateSecurityExceptions(root, failures, currentDate) {
  const manifestPath = path.join(root, SECURITY_EXCEPTION_MANIFEST);
  if (!fs.existsSync(manifestPath)) {
    readText(root, SECURITY_EXCEPTION_MANIFEST, failures);
    return;
  }
  const manifest = loadYaml(root, SECURITY_EXCEPTION_MANIFEST, failures);
  requireValue(
    failures,
    manifest?.schema_version === 1,
    `${SECURITY_EXCEPTION_MANIFEST}: schema_version must be 1`,
  );
  if (!Array.isArray(manifest?.exceptions)) {
    failures.push(`${SECURITY_EXCEPTION_MANIFEST}: exceptions must be an array`);
    return;
  }

  const effectiveDate =
    currentDate instanceof Date
      ? currentDate.toISOString().slice(0, 10)
      : (currentDate ?? new Date().toISOString().slice(0, 10));
  const currentMilliseconds = exactUtcDate(effectiveDate);
  if (currentMilliseconds === undefined) {
    failures.push(`${SECURITY_EXCEPTION_MANIFEST}: currentDate must use YYYY-MM-DD`);
    return;
  }

  const identifiers = new Set();
  for (const [index, exception] of manifest.exceptions.entries()) {
    const label = exceptionLabel(exception, index);
    if (exception === null || typeof exception !== "object" || Array.isArray(exception)) {
      failures.push(`${SECURITY_EXCEPTION_MANIFEST}: ${label} must be an object`);
      continue;
    }

    for (const field of [
      "id",
      "scanner",
      "finding_id",
      "severity",
      "scope",
      "disposition",
      "rationale",
      "owner",
      "tracking_ref",
      "approved_on",
      "expires_on",
    ]) {
      validRequiredText(exception, field, label, failures);
    }

    const identifierValid =
      typeof exception.id === "string" &&
      SECURITY_EXCEPTION_ID_PATTERN.test(exception.id) &&
      exception.id.length <= 100;
    requireValue(
      failures,
      identifierValid,
      `${SECURITY_EXCEPTION_MANIFEST}: ${label} id must use stable kebab-case with at most 100 characters`,
    );
    if (identifierValid) {
      requireValue(
        failures,
        !identifiers.has(exception.id),
        `${SECURITY_EXCEPTION_MANIFEST}: duplicate id ${exception.id}`,
      );
      identifiers.add(exception.id);
    }
    requireValue(
      failures,
      SECURITY_EXCEPTION_SEVERITIES.has(exception.severity),
      `${SECURITY_EXCEPTION_MANIFEST}: ${label} severity is invalid`,
    );
    requireValue(
      failures,
      SECURITY_EXCEPTION_DISPOSITIONS.has(exception.disposition),
      `${SECURITY_EXCEPTION_MANIFEST}: ${label} disposition is invalid`,
    );
    requireValue(
      failures,
      safeTrackingReference(exception.tracking_ref),
      `${SECURITY_EXCEPTION_MANIFEST}: ${label} tracking_ref must be a safe GitHub issue, advisory, or alert identifier`,
    );

    const approvedMilliseconds = exactUtcDate(exception.approved_on);
    const expiresMilliseconds = exactUtcDate(exception.expires_on);
    requireValue(
      failures,
      approvedMilliseconds !== undefined,
      `${SECURITY_EXCEPTION_MANIFEST}: ${label} approved_on must use an exact YYYY-MM-DD calendar date`,
    );
    requireValue(
      failures,
      expiresMilliseconds !== undefined,
      `${SECURITY_EXCEPTION_MANIFEST}: ${label} expires_on must use an exact YYYY-MM-DD calendar date`,
    );
    if (approvedMilliseconds !== undefined && expiresMilliseconds !== undefined) {
      requireValue(
        failures,
        expiresMilliseconds > approvedMilliseconds,
        `${SECURITY_EXCEPTION_MANIFEST}: ${label} expires_on must be after approved_on`,
      );
      requireValue(
        failures,
        (expiresMilliseconds - approvedMilliseconds) / DAY_IN_MILLISECONDS <= 90,
        `${SECURITY_EXCEPTION_MANIFEST}: ${label} exception window must not exceed 90 days`,
      );
      requireValue(
        failures,
        currentMilliseconds < expiresMilliseconds,
        `${SECURITY_EXCEPTION_MANIFEST}: ${label} exception is expired`,
      );
    }
    if (approvedMilliseconds !== undefined) {
      requireValue(
        failures,
        approvedMilliseconds <= currentMilliseconds,
        `${SECURITY_EXCEPTION_MANIFEST}: ${label} approved_on cannot be in the future`,
      );
    }

    const suppression = exception.suppression;
    if (suppression === null || typeof suppression !== "object" || Array.isArray(suppression)) {
      failures.push(`${SECURITY_EXCEPTION_MANIFEST}: ${label} suppression must be an object`);
      continue;
    }
    if (suppression.kind === "repository-file") {
      const pathIsSafe = safeRepositoryPath(suppression.path);
      requireValue(
        failures,
        pathIsSafe,
        `${SECURITY_EXCEPTION_MANIFEST}: ${label} suppression.path must be a safe repository-relative path`,
      );
      if (pathIsSafe) {
        const target = path.join(root, suppression.path);
        const targetIsFile = fs.existsSync(target) && fs.statSync(target).isFile();
        requireValue(
          failures,
          targetIsFile,
          `${SECURITY_EXCEPTION_MANIFEST}: ${label} suppression target is missing`,
        );
        if (targetIsFile) {
          const rootRealPath = fs.realpathSync(root);
          const targetRealPath = fs.realpathSync(target);
          const manifestRealPath = fs.realpathSync(manifestPath);
          const relativeTarget = path.relative(rootRealPath, targetRealPath);
          const targetIsInsideCheckout =
            relativeTarget !== "" &&
            !path.isAbsolute(relativeTarget) &&
            relativeTarget !== ".." &&
            !relativeTarget.startsWith(`..${path.sep}`);
          requireValue(
            failures,
            targetIsInsideCheckout,
            `${SECURITY_EXCEPTION_MANIFEST}: ${label} suppression target must stay inside the checkout`,
          );
          const targetsManifest = targetRealPath === manifestRealPath;
          requireValue(
            failures,
            !targetsManifest,
            `${SECURITY_EXCEPTION_MANIFEST}: ${label} exception manifest cannot be its native suppression`,
          );
          if (!targetIsInsideCheckout || targetsManifest) continue;
          requireValue(
            failures,
            hasSecurityExceptionMarker(fs.readFileSync(target, "utf8"), exception.id),
            `${SECURITY_EXCEPTION_MANIFEST}: ${label} suppression marker is missing`,
          );
        }
      }
    } else if (suppression.kind === "github-code-scanning-alert") {
      requireValue(
        failures,
        typeof suppression.url === "string" &&
          /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/security\/code-scanning\/[1-9]\d*$/.test(
            suppression.url,
          ),
        `${SECURITY_EXCEPTION_MANIFEST}: ${label} suppression.url must identify an exact GitHub code-scanning alert`,
      );
    } else {
      failures.push(`${SECURITY_EXCEPTION_MANIFEST}: ${label} suppression.kind is invalid`);
    }
  }
}

function needs(job, dependency) {
  const value = job?.needs;
  return value === dependency || (Array.isArray(value) && value.includes(dependency));
}

function normalizedExpression(value) {
  return String(value ?? "").replaceAll(/\s+/g, " ").trim();
}

function hasExactMapping(value, expected) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const actualKeys = Object.keys(value).sort();
  const expectedKeys = Object.keys(expected).sort();
  return (
    JSON.stringify(actualKeys) === JSON.stringify(expectedKeys) &&
    expectedKeys.every((key) => value[key] === expected[key])
  );
}

const VERIFICATION_JOBS = [
  "documentation",
  "python",
  "unit",
  "integration",
  "contract",
  "browser",
  "image",
];
const BROWSER_EVIDENCE_UPLOAD_ACTION =
  "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02";
const BROWSER_EVIDENCE_OUTPUTS = [
  "packages/builtin-ui/web/browser-evidence/report",
  "packages/builtin-ui/web/browser-evidence/results",
  "packages/builtin-ui/web/browser-evidence/provenance.json",
];
const STABLE_PUBLICATION_CONCURRENCY_GROUP = "stable-container-publication";
const RELEASE_PUBLICATION_STEP_NAME = "Publish and verify stable image";
const RELEASE_PUBLICATION_COMMAND = "node scripts/release-publication.mjs";
const RELEASE_PUBLICATION_EVIDENCE_ACTION =
  "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02";
const RELEASE_PREPARATION_WORKFLOW_PATH = ".github/workflows/prepare-release.yaml";
const RELEASE_CONTROLLER_CONCURRENCY_GROUP = "release-controller";
const RELEASE_CONTROLLER_STEP_NAME = "Request stable release";
const RELEASE_CONTROLLER_ACTION =
  "actions/github-script@ed597411d8f924073f98dfc5c65a23a2325f34cd";
const RELEASE_CONTROLLER_SCRIPT_COMMAND = "scripts/release-automation.mjs";

const WORKSPACE_DISTRIBUTIONS = [
  "media-finder",
  "media-finder-core",
  "media-finder-module-sdk",
  "media-finder-control-contracts",
  "media-finder-builtin-ui",
  "media-finder-metadata-manual",
  "media-finder-metadata-tmdb",
  "media-finder-release-prowlarr",
  "media-finder-download-qbittorrent",
];

const FIRST_PARTY_MODULE_MANIFESTS = [
  "packages/modules/metadata-manual/src/media_finder_metadata_manual/module.toml",
  "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb/module.toml",
  "packages/modules/release-prowlarr/src/media_finder_release_prowlarr/module.toml",
  "packages/modules/download-qbittorrent/src/media_finder_download_qbittorrent/module.toml",
];
const COMPOSE_MODULE_ENVIRONMENT_BEGIN = "# BEGIN FIRST-PARTY MODULE ENVIRONMENT";
const COMPOSE_MODULE_ENVIRONMENT_END = "# END FIRST-PARTY MODULE ENVIRONMENT";
const DOCS_MODULE_ENVIRONMENT_BEGIN = "<!-- BEGIN FIRST-PARTY MODULE ENVIRONMENT -->";
const DOCS_MODULE_ENVIRONMENT_END = "<!-- END FIRST-PARTY MODULE ENVIRONMENT -->";

function stepByName(job, name) {
  return (job?.steps ?? []).find((step) => step.name === name);
}

function pytestInvocations(command) {
  const normalized = String(command ?? "").replaceAll(/\s+/g, " ").trim();
  return normalized
    .split(/\s*(?:&&|\|\||;)\s*/)
    .map((segment) =>
      segment.match(/^(?:uv run )?(?:(?:python|python3) -m )?pytest\b(?<arguments>.*)$/),
    )
    .filter(Boolean)
    .map((match) => String(match.groups?.arguments ?? ""));
}

function runsPytest(step, requiredPaths) {
  return pytestInvocations(step?.run).some((invocationArguments) =>
    requiredPaths.every((required) => invocationArguments.includes(required)),
  );
}

function runsShellCommand(step, expected) {
  return String(step?.run ?? "")
    .split(/\s*(?:\r?\n|&&|\|\||;)\s*/)
    .some((command) => command.trim() === expected);
}

function testPathsFromCommands(verify) {
  const paths = new Set();
  for (const job of Object.values(verify.jobs ?? {})) {
    for (const step of job.steps ?? []) {
      for (const arguments_ of pytestInvocations(step.run)) {
        for (const match of arguments_.matchAll(/\b(?:tests|packages)\/[A-Za-z0-9_./-]+/g)) {
          const candidate = match[0].replace(/[.,:;]+$/, "");
          if (candidate.includes("/tests") || candidate.startsWith("tests/")) {
            paths.add(candidate);
          }
        }
      }
    }
  }
  return paths;
}

function recursivelyListTests(root) {
  const files = [];
  function visit(directory) {
    if (!fs.existsSync(directory)) return;
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(target);
      else if (/^test_.*\.py$/.test(entry.name)) files.push(target);
    }
  }
  visit(path.join(root, "tests"));
  return files;
}

function containsCredentialReference(value, key = "") {
  if (
    key.startsWith("RELEASE_APP_") ||
    (key !== "persist-credentials" &&
      /(?:^|[_-])(token|secret|password|private[_-]?key|credential(?:s)?|authorization)(?:$|[_-])/i.test(key))
  ) {
    return true;
  }
  if (typeof value === "string") {
    return /\$\{\{\s*(?:secrets\.|github\.token\b)/.test(value);
  }
  if (value === null || typeof value !== "object") return false;
  return Object.entries(value).some(([childKey, childValue]) =>
    containsCredentialReference(childValue, childKey),
  );
}

function hasExactKeys(value, expectedKeys) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  return JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...expectedKeys].sort());
}

function validateReleasePreparationWorkflow(root, failures) {
  const workflowText = readText(root, RELEASE_PREPARATION_WORKFLOW_PATH, failures);
  if (!workflowText) return;

  let workflow;
  try {
    workflow = YAML.parse(workflowText) ?? {};
  } catch {
    failures.push(`${RELEASE_PREPARATION_WORKFLOW_PATH}: invalid YAML`);
    return;
  }

  const dispatch = workflow.on?.workflow_dispatch;
  requireValue(
    failures,
    hasExactKeys(workflow.on, ["workflow_dispatch"]),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: stable release preparation must use workflow_dispatch only`,
  );
  requireValue(
    failures,
    dispatch !== null && typeof dispatch === "object" && !Array.isArray(dispatch),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: workflow_dispatch configuration is required`,
  );
  requireValue(
    failures,
    hasExactKeys(dispatch?.inputs, ["version"]),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: workflow_dispatch must expose only the version input`,
  );
  const versionInput = dispatch?.inputs?.version;
  requireValue(
    failures,
    versionInput?.required === true && versionInput?.type === "string",
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: version input must be a required string`,
  );

  requireValue(
    failures,
    hasExactMapping(workflow.permissions, { actions: "read", contents: "read" }),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: workflow token permissions must be limited to actions read and contents read`,
  );
  requireValue(
    failures,
    workflow.concurrency?.group === RELEASE_CONTROLLER_CONCURRENCY_GROUP,
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller concurrency must use the constant repository-wide group`,
  );
  requireValue(
    failures,
    workflow.concurrency?.["cancel-in-progress"] === false,
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller concurrency must not cancel in-progress runs`,
  );

  const jobs = workflow.jobs;
  const jobNames = jobs && typeof jobs === "object" && !Array.isArray(jobs) ? Object.keys(jobs) : [];
  requireValue(
    failures,
    jobNames.length === 1 && jobNames[0] === "release",
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: trusted release controller must be the only job`,
  );
  const job = jobs?.release;
  requireValue(
    failures,
    normalizedExpression(job?.if) ===
      "${{ github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' }}",
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller job must guard workflow_dispatch on main`,
  );
  requireValue(
    failures,
    job?.["timeout-minutes"] === 330,
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller job must have a 330-minute timeout`,
  );
  requireValue(
    failures,
    job?.permissions === undefined ||
      hasExactMapping(job.permissions, { actions: "read", contents: "read" }),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller job permissions must remain read-only`,
  );
  requireValue(
    failures,
    job?.["continue-on-error"] !== true &&
      !(job?.steps ?? []).some((step) => step?.["continue-on-error"] === true),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller failures must not be masked`,
  );
  requireValue(
    failures,
    !containsCredentialReference(workflow.env),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: credentials must not be configured at workflow scope`,
  );
  requireValue(
    failures,
    !containsCredentialReference(job?.env),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: credentials must not be configured at job scope`,
  );

  const steps = Array.isArray(job?.steps) ? job.steps : [];
  const stepIndex = (predicate) => steps.findIndex(predicate);
  const checkoutIndex = stepIndex((step) => String(step?.uses ?? "").startsWith("actions/checkout@"));
  const pythonIndex = stepIndex((step) => String(step?.uses ?? "").startsWith("actions/setup-python@"));
  const pnpmIndex = stepIndex((step) => String(step?.uses ?? "").startsWith("pnpm/action-setup@"));
  const nodeIndex = stepIndex((step) => String(step?.uses ?? "").startsWith("actions/setup-node@"));
  const uvIndex = stepIndex((step) => String(step?.uses ?? "").startsWith("astral-sh/setup-uv@"));
  const controllerIndexes = steps
    .map((step, index) => (step?.name === RELEASE_CONTROLLER_STEP_NAME ? index : -1))
    .filter((index) => index >= 0);
  const controllerIndex = controllerIndexes[0] ?? -1;
  const controller = controllerIndex >= 0 ? steps[controllerIndex] : undefined;
  const checkout = checkoutIndex >= 0 ? steps[checkoutIndex] : undefined;
  const pythonSetup = pythonIndex >= 0 ? steps[pythonIndex] : undefined;
  const pnpmSetup = pnpmIndex >= 0 ? steps[pnpmIndex] : undefined;
  const nodeSetup = nodeIndex >= 0 ? steps[nodeIndex] : undefined;
  const uvSetup = uvIndex >= 0 ? steps[uvIndex] : undefined;

  requireValue(
    failures,
    checkoutIndex >= 0 &&
      checkout?.with?.ref === "${{ github.sha }}" &&
      checkout?.with?.["fetch-depth"] === 0 &&
      checkout?.with?.["persist-credentials"] === false,
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: trusted checkout must use github.sha, complete history, and no persisted credentials`,
  );
  requireValue(
    failures,
    pythonIndex >= 0 && pythonSetup?.with?.["python-version"] === "3.13",
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller must use the pinned Python 3.13 toolchain`,
  );
  requireValue(
    failures,
    pnpmIndex >= 0 &&
      pnpmSetup?.with?.version === "11.19.0" &&
      pnpmSetup?.with?.run_install === false,
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller must use the pinned pnpm toolchain without implicit install`,
  );
  requireValue(
    failures,
    nodeIndex >= 0 && nodeSetup?.with?.["node-version"] === "24",
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller must use the pinned Node 24 toolchain`,
  );
  requireValue(
    failures,
    uvIndex >= 0 && uvSetup?.with?.version === "0.12.5",
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller must use the pinned uv 0.12.5 toolchain`,
  );

  const uvInstallIndex = stepIndex((step) => runsShellCommand(step, "uv sync --frozen --all-groups"));
  const pnpmInstallIndex = stepIndex((step) => runsShellCommand(step, "pnpm install --frozen-lockfile"));
  requireValue(
    failures,
    uvInstallIndex >= 0 && pnpmInstallIndex >= 0 &&
      controllerIndex > uvInstallIndex && controllerIndex > pnpmInstallIndex,
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: frozen Python and Node installs must complete before credentials are exposed`,
  );

  requireValue(
    failures,
    controllerIndexes.length === 1 && controllerIndex === steps.length - 1,
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: the trusted controller must be the final single step`,
  );
  requireValue(
    failures,
    controller?.uses === RELEASE_CONTROLLER_ACTION,
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: final controller step must use the pinned github-script action`,
  );
  requireValue(
    failures,
    hasExactMapping(controller?.env, {
      RELEASE_APP_CLIENT_ID: "${{ vars.RELEASE_APP_CLIENT_ID }}",
      RELEASE_APP_PRIVATE_KEY: "${{ secrets.RELEASE_APP_PRIVATE_KEY }}",
      RELEASE_EVIDENCE_PATH: "${{ runner.temp }}/release-evidence.json",
      RELEASE_VERSION: "${{ inputs.version }}",
    }),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: App credentials must be confined to the final controller environment`,
  );
  requireValue(
    failures,
    hasExactKeys(controller?.with, ["script"]) && typeof controller?.with?.script === "string",
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: final controller must provide only its trusted script`,
  );
  const controllerScript = String(controller?.with?.script ?? "");
  requireValue(
    failures,
    /exec\.exec\(\s*"node"\s*,\s*\[\s*"scripts\/release-automation\.mjs"\s*,\s*"--phase"\s*,\s*"request"\s*,\s*"--version"\s*,\s*process\.env\.RELEASE_VERSION\s*,?\s*\]/s.test(
        controllerScript,
      ),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller must invoke the fixed request command with an argument array`,
  );
  requireValue(
    failures,
    !controllerScript.includes("${{") && !controllerScript.includes("shell") && !controllerScript.includes("sh -c"),
    `${RELEASE_PREPARATION_WORKFLOW_PATH}: controller script must not interpolate inputs or invoke a shell`,
  );

  for (const [index, step] of steps.entries()) {
    if (index === controllerIndex) continue;
    requireValue(
      failures,
      !containsCredentialReference(step),
      `${RELEASE_PREPARATION_WORKFLOW_PATH}: candidate and setup steps must not receive release credentials`,
    );
    requireValue(
      failures,
      !String(step?.run ?? "").includes(RELEASE_CONTROLLER_SCRIPT_COMMAND) &&
        !String(step?.run ?? "").includes("scripts/prepare-release.py"),
      `${RELEASE_PREPARATION_WORKFLOW_PATH}: candidate scripts must run only inside the trusted controller`,
    );
  }
}

function validateActionPins(workflows, failures) {
  const immutableAction = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\/[^@\s]+)?@[0-9a-f]{40}$/;
  for (const [workflowPath, workflow] of workflows) {
    requireValue(
      failures,
      workflow.permissions?.packages !== "write",
      `${workflowPath}: packages write permission must not be workflow-wide`,
    );
    for (const [jobName, job] of Object.entries(workflow.jobs ?? {})) {
      const usages = [];
      if (job.uses) usages.push(job.uses);
      for (const step of job.steps ?? []) {
        if (step.uses) usages.push(step.uses);
      }
      for (const usage of usages) {
        if (String(usage).startsWith("./")) continue;
        requireValue(
          failures,
          immutableAction.test(String(usage)),
          `${workflowPath}: ${jobName} must pin ${usage} to an immutable 40-character commit SHA`,
        );
      }
      if (job.permissions?.packages === "write") {
        const allowed =
          (workflowPath === ".github/workflows/ci.yaml" && jobName === "publish-edge") ||
          (workflowPath === ".github/workflows/release.yaml" &&
            (jobName === "publish" || jobName === "repair"));
        requireValue(
          failures,
          allowed,
          `${workflowPath}: packages write permission is only allowed on a gated publish job`,
        );
      }
    }
  }
}

function firstPartyModuleManifests(root, failures) {
  const manifests = [];
  for (const relativePath of FIRST_PARTY_MODULE_MANIFESTS) {
    const content = readText(root, relativePath, failures);
    if (!content) continue;
    try {
      manifests.push(parseToml(content));
    } catch (error) {
      failures.push(`${relativePath}: invalid TOML (${error.message})`);
    }
  }
  return manifests;
}

function manifestEnvironmentNames(manifests) {
  return manifests.flatMap((manifest) =>
    (Array.isArray(manifest.environment) ? manifest.environment : []).map((declaration) =>
      String(declaration.name),
    ),
  );
}

function markedBlock(content, begin, end) {
  const start = content.indexOf(begin);
  if (start === -1) return undefined;
  const finish = content.indexOf(end, start + begin.length);
  if (finish === -1) return undefined;
  return content.slice(start, finish + end.length).replaceAll("\r\n", "\n").trim();
}

function expectedModuleEnvironmentDocumentation(manifests) {
  const rows = [];
  for (const manifest of manifests) {
    const declarations = Array.isArray(manifest.environment) ? manifest.environment : [];
    if (declarations.length === 0) {
      rows.push(
        `| \`${manifest.module_id}\` | \`${manifest.module_kind}\` | Configuration-free | — | — |`,
      );
      continue;
    }
    for (const declaration of declarations) {
      rows.push(
        `| \`${manifest.module_id}\` | \`${manifest.module_kind}\` | \`${declaration.name}\` | ${declaration.required === true ? "Yes" : "No"} | ${declaration.secret === true ? "Yes" : "No"} |`,
      );
    }
  }
  return [
    DOCS_MODULE_ENVIRONMENT_BEGIN,
    "| Module ID | Kind | Variable | Required for module | Secret |",
    "| --- | --- | --- | --- | --- |",
    ...rows,
    DOCS_MODULE_ENVIRONMENT_END,
  ].join("\n");
}

function validateCompose(root, failures) {
  const manifests = firstPartyModuleManifests(root, failures);
  const integrationVariables = manifestEnvironmentNames(manifests);
  const compose = loadYaml(root, "compose.example.yaml", failures);
  const composeText = readText(root, "compose.example.yaml", failures);
  const services = compose.services ?? {};
  const serviceNames = Object.keys(services);
  requireValue(
    failures,
    serviceNames.length === 1,
    "compose.example.yaml: exactly one service is required",
  );
  const service = services[serviceNames[0]] ?? {};
  const environment = service.environment ?? {};
  requireValue(
    failures,
    typeof service.image === "string" && service.image.startsWith("ghcr.io/"),
    "compose.example.yaml: service must use a GHCR image",
  );
  for (const name of integrationVariables) {
    requireValue(
      failures,
      Object.hasOwn(environment, name),
      `compose.example.yaml: exact integration variable ${name} is required`,
    );
  }
  const composeEnvironmentBlock = markedBlock(
    composeText,
    COMPOSE_MODULE_ENVIRONMENT_BEGIN,
    COMPOSE_MODULE_ENVIRONMENT_END,
  );
  const markedVariableNames = [...(composeEnvironmentBlock ?? "").matchAll(/^\s*([A-Z][A-Z0-9_]+):/gm)].map(
    (match) => match[1],
  );
  requireValue(
    failures,
    JSON.stringify(markedVariableNames) === JSON.stringify(integrationVariables),
    `compose.example.yaml: first-party module environment block must match manifests (expected: ${integrationVariables.join(", ")})`,
  );
  requireValue(
    failures,
    Object.hasOwn(environment, "MEDIA_FINDER_UI_MODE") &&
      String(environment.MEDIA_FINDER_UI_MODE).includes("builtin"),
    "compose.example.yaml: MEDIA_FINDER_UI_MODE must default to builtin",
  );
  for (const obsolete of ["TMDB_API_TOKEN", "QB_USERNAME", "QB_PASSWORD"]) {
    requireValue(
      failures,
      !Object.hasOwn(environment, obsolete),
      `compose.example.yaml: obsolete integration variable ${obsolete} is forbidden`,
    );
  }
  const operationsDocumentation = readText(root, "docs/operations.md", failures);
  const operatorDocumentation = [readText(root, "README.md", failures), operationsDocumentation].join(
    "\n",
  );
  requireValue(
    failures,
    markedBlock(
      operationsDocumentation,
      DOCS_MODULE_ENVIRONMENT_BEGIN,
      DOCS_MODULE_ENVIRONMENT_END,
    ) === expectedModuleEnvironmentDocumentation(manifests),
    "docs/operations.md: module environment documentation must match first-party manifests",
  );
  requireValue(
    failures,
    !operatorDocumentation.includes("Store the corresponding `env:VARIABLE_NAME` reference"),
    "operator documentation: persisted integration settings guidance is forbidden",
  );
  requireValue(
    failures,
    (service.ports ?? []).some((port) => String(port).startsWith("127.0.0.1:")),
    "compose.example.yaml: default port must bind to localhost",
  );
  requireValue(
    failures,
    (service.volumes ?? []).some((volume) => String(volume).endsWith(":/data")),
    "compose.example.yaml: a named volume must mount at /data",
  );
  requireValue(
    failures,
    Boolean(service.healthcheck?.test),
    "compose.example.yaml: healthcheck is required",
  );
  requireValue(
    failures,
    Boolean(service.user),
    "compose.example.yaml: an explicit non-root user is required",
  );
  for (const volume of service.volumes ?? []) {
    const target = typeof volume === "string" ? volume.split(":").at(-1) : volume.target;
    requireValue(
      failures,
      target !== "/downloads" && target !== "/media",
      `compose.example.yaml: forbidden media mount ${target}`,
    );
  }
  const normalizedComposeText = composeText.toLowerCase();
  for (const forbidden of ["traefik", "tinyauth", "hametov.uk"]) {
    requireValue(
      failures,
      !normalizedComposeText.includes(forbidden),
      `compose.example.yaml: forbidden private assumption ${forbidden}`,
    );
  }
}

function dockerStages(dockerfile) {
  const stages = [];
  let currentStage;
  const lines = dockerfile.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (/^\s*(?:#|$)/.test(line)) continue;
    const match = line.match(/^\s*(?<keyword>[A-Z]+)\s+(?<command>.*)$/);
    if (!match) continue;
    let command = match.groups.command;
    while (/\\\s*$/.test(command) && index + 1 < lines.length) {
      command = command.replace(/\\\s*$/, " ");
      index += 1;
      command += lines[index].trim();
    }
    if (match.groups.keyword === "FROM") {
      const stageName = command.match(/\s+AS\s+(?<name>[A-Za-z][A-Za-z0-9_-]*)$/i)?.groups.name;
      currentStage = { name: stageName, command, instructions: [] };
      stages.push(currentStage);
    } else if (currentStage) {
      currentStage.instructions.push({ keyword: match.groups.keyword, command });
    }
  }
  return stages;
}

function validateImage(root, verify, verifyText, failures) {
  const dockerfile = readText(root, "Dockerfile", failures);
  const stages = dockerStages(dockerfile);
  const runtimeStage = stages.at(-1);
  const runtimeVenvCopy = runtimeStage?.instructions.find(
    (instruction) =>
      instruction.keyword === "COPY" &&
      /^--from=(?<source>[A-Za-z][A-Za-z0-9_-]*)\s+\/opt\/venv\s+\/opt\/venv$/.test(
        instruction.command,
      ),
  );
  const sourceStageName = runtimeVenvCopy?.command.match(/^--from=(?<source>[A-Za-z][A-Za-z0-9_-]*)/)?.groups
    .source;
  const builderStage = stages.find((stage) => stage.name === sourceStageName);
  const builderRun = builderStage?.instructions.find(
    (instruction) =>
      instruction.keyword === "RUN" && instruction.command.includes("mkdir /wheels"),
  )?.command;
  requireValue(
    failures,
    stages.length >= 2,
    "Dockerfile: multi-stage build required",
  );
  requireValue(
    failures,
    runtimeStage?.command.startsWith("python:"),
    "Dockerfile: runtime image must remain Python-only",
  );
  requireValue(
    failures,
    runtimeStage?.instructions.some(
      (instruction) => instruction.keyword === "USER" && instruction.command === "10001:10001",
    ),
    "Dockerfile: runtime must use UID/GID 10001",
  );
  requireValue(
    failures,
    runtimeStage?.instructions.some(
      (instruction) =>
        instruction.keyword === "ENTRYPOINT" &&
        instruction.command === '["python", "-m", "media_finder_server"]',
    ),
    "Dockerfile: runtime entrypoint must gate startup",
  );
  requireValue(
    failures,
    /for distribution in\s+media-finder\s+media-finder-core\s+media-finder-module-sdk\s+media-finder-control-contracts\s+media-finder-builtin-ui\s+media-finder-metadata-manual\s+media-finder-metadata-tmdb\s+media-finder-release-prowlarr\s+media-finder-download-qbittorrent\s+; do\s+uv build --wheel --package "\$distribution" --out-dir \/wheels/.test(
      builderRun,
    ),
    "Dockerfile: production image must build every workspace package as wheels",
  );
  requireValue(
    failures,
    builderRun?.includes("uv venv --python /usr/local/bin/python /opt/venv") &&
      builderRun.includes("uv export --locked --package media-finder") &&
      builderRun.includes("--no-emit-project") &&
      builderRun.includes("--no-emit-workspace") &&
      !builderRun.includes("--no-hashes") &&
      builderRun.includes(
        "uv pip install --python /opt/venv/bin/python --require-hashes -r /tmp/runtime-requirements.txt",
      ) &&
      builderRun.includes("uv pip install --python /opt/venv/bin/python --no-deps /wheels/*.whl") &&
      sourceStageName === "builder" &&
      runtimeVenvCopy?.command === "--from=builder /opt/venv /opt/venv" &&
      !builderStage?.instructions.some(
        (instruction) => instruction.keyword === "RUN" && instruction.command.includes("uv sync --frozen"),
      ),
    "Dockerfile: production image must install every workspace wheel into a fresh runtime venv",
  );
  requireValue(
    failures,
    builderRun?.includes("uv export --locked --package media-finder") &&
      !builderRun.includes("--no-hashes") &&
      builderRun.includes("--require-hashes -r /tmp/runtime-requirements.txt"),
    "Dockerfile: production image must install locked requirements with hashes",
  );

  const imageJob = verify.jobs?.image;
  const smokeStep = (imageJob?.steps ?? []).find(
    (step) => step.name === "Exercise production image",
  );
  requireValue(
    failures,
    smokeStep?.run === "bash scripts/smoke-container.sh",
    ".github/workflows/verify.yaml: image job must run the production smoke script",
  );
  readText(root, "scripts/verify-image.py", failures);
  const smoke = readText(root, "scripts/smoke-container.sh", failures);
  requireValue(
    failures,
    smoke.includes('docker exec -i "$container_name" python -I - < scripts/verify-image.py'),
    "scripts/smoke-container.sh: image smoke must execute scripts/verify-image.py",
  );
  const expectations = [
    ["UI root", /assert_response\s+"UI root"\s+"\$base_url\/"\s+"200"\s+"<!doctype html>"/],
    [
      "/health/live",
      /assert_response\s+"Liveness"\s+"\$base_url\/health\/live"\s+"200"\s+'\{"status":"live"\}'/,
    ],
    [
      "/health/ready",
      /assert_response\s+"Readiness"\s+"\$base_url\/health\/ready"\s+"200"\s+'\{"status":"ready"\}'/,
    ],
    [
      "unauthorized /api/v1",
      /"Unauthorized processor API"[\s\S]+?"401"[\s\S]+?'"code":"authentication_required"'/,
    ],
    [
      "authorized /api/v1",
      /"Authorized processor API"[\s\S]+?"404"[\s\S]+?'"code":"media_item_not_found"'[\s\S]+?Authorization: Bearer ci-integration-token/,
    ],
    [
      "browser control API",
      /"Browser control session"[\s\S]+?\/api\/control\/v1\/session[\s\S]+?"200"/,
    ],
    [
      "disabled UI mode",
      /MEDIA_FINDER_UI_MODE=disabled[\s\S]+?"Disabled UI root"[\s\S]+?"404"[\s\S]+?"Disabled control session"[\s\S]+?"200"/,
    ],
  ];
  for (const [label, pattern] of expectations) {
    requireValue(
      failures,
      pattern.test(smoke),
      `scripts/smoke-container.sh: image smoke test must validate ${label}`,
    );
  }
  requireValue(
    failures,
    /docker exec "\$container_name" id -u/.test(smoke) &&
      /docker exec "\$container_name" id -g/.test(smoke),
    "scripts/smoke-container.sh: image smoke test must validate UID and GID",
  );
  requireValue(
    failures,
    verifyText.includes("packages/builtin-ui/src/media_finder_builtin_ui/static"),
    ".github/workflows/verify.yaml: built-in UI asset drift check is required",
  );
}

function validateVerification(root, verify, verifyText, failures) {
  requireValue(
    failures,
    Object.hasOwn(verify.on ?? {}, "workflow_call"),
    ".github/workflows/verify.yaml: reusable verification must use workflow_call",
  );
  requireValue(
    failures,
    verify.env?.UV_CACHE_DIR === "${{ github.workspace }}/.tools/uv-cache",
    ".github/workflows/verify.yaml: repository-local uv cache must be seeded for offline isolation runners",
  );
  requireValue(
    failures,
    JSON.stringify(Object.keys(verify.jobs ?? {}).sort()) ===
      JSON.stringify([...VERIFICATION_JOBS].sort()),
    ".github/workflows/verify.yaml: exactly the seven protected job identifiers are required",
  );
  for (const job of VERIFICATION_JOBS) {
    requireValue(
      failures,
      Boolean(verify.jobs?.[job]),
      `.github/workflows/verify.yaml: missing ${job} job`,
    );
  }
  const releaseScriptTests = stepByName(
    verify.jobs?.documentation,
    "Test release automation scripts",
  );
  requireValue(
    failures,
    releaseScriptTests?.run ===
      "node --test scripts/release-publication.test.mjs scripts/release-automation.test.mjs",
    ".github/workflows/verify.yaml: documentation job must run release-publication.test.mjs and release-automation.test.mjs",
  );
  const unitCommands = (verify.jobs?.unit?.steps ?? []).map((step) => step.run ?? "").join("\n");
  const browserCommands = (verify.jobs?.browser?.steps ?? [])
    .map((step) => step.run ?? "")
    .join("\n");
  requireValue(
    failures,
    unitCommands
      .split("\n")
      .some(
        (line) =>
          line.trim() === "uv run python packages/builtin-ui/tests/run_isolated.py unit",
      ),
    ".github/workflows/verify.yaml: unit job must run the wheel-only built-in UI suite",
  );
  requireValue(
    failures,
    browserCommands
      .split("\n")
      .some((line) => line.trim() === "pnpm ui:browser"),
    ".github/workflows/verify.yaml: browser job must run the Playwright built-in UI suite",
  );
  const browser = verify.jobs?.browser;
  const browserTestStep = (browser?.steps ?? []).find((step) => step.id === "browser-tests");
  requireValue(
    failures,
    browserTestStep?.run === "pnpm ui:browser",
    ".github/workflows/verify.yaml: browser tests must use the browser-tests step identity",
  );
  requireValue(
    failures,
    browser?.["continue-on-error"] !== true && browserTestStep?.["continue-on-error"] !== true,
    ".github/workflows/verify.yaml: browser test failure must not be masked",
  );
  const provenanceStep = (browser?.steps ?? []).find(
    (step) => step.name === "Generate browser evidence",
  );
  requireValue(
    failures,
    provenanceStep?.if === "${{ always() }}" &&
      provenanceStep?.run === "node packages/builtin-ui/scripts/browser-evidence.mjs" &&
      provenanceStep?.env?.BROWSER_TEST_OUTCOME === "${{ steps.browser-tests.outcome }}",
    ".github/workflows/verify.yaml: browser evidence provenance must run after browser tests with their outcome",
  );
  requireValue(
    failures,
    provenanceStep?.env?.MF_EVENT_SHA === "${{ github.sha }}" &&
      provenanceStep?.env?.MF_PR_HEAD_SHA === "${{ github.event.pull_request.head.sha }}" &&
      provenanceStep?.env?.MF_PR_BASE_SHA === "${{ github.event.pull_request.base.sha }}",
    ".github/workflows/verify.yaml: browser evidence provenance must record the exact event and pull-request commit expressions",
  );
  const evidenceUpload = (browser?.steps ?? []).find(
    (step) => step.name === "Upload browser evidence",
  );
  requireValue(
    failures,
    Boolean(evidenceUpload),
    ".github/workflows/verify.yaml: browser job must upload browser evidence",
  );
  requireValue(
    failures,
    evidenceUpload?.uses === BROWSER_EVIDENCE_UPLOAD_ACTION,
    ".github/workflows/verify.yaml: browser evidence upload must use the approved immutable upload-artifact SHA",
  );
  requireValue(
    failures,
    evidenceUpload?.if === "${{ always() }}",
    ".github/workflows/verify.yaml: browser evidence upload must run with always()",
  );
  const browserSteps = browser?.steps ?? [];
  const browserTestIndex = browserSteps.indexOf(browserTestStep);
  const provenanceIndex = browserSteps.indexOf(provenanceStep);
  const evidenceUploadIndex = browserSteps.indexOf(evidenceUpload);
  requireValue(
    failures,
    browserTestIndex >= 0 &&
      provenanceIndex > browserTestIndex &&
      evidenceUploadIndex > provenanceIndex,
    ".github/workflows/verify.yaml: browser tests, provenance, and upload must run in that order",
  );
  requireValue(
    failures,
    [browserTestStep, provenanceStep, evidenceUpload].every(
      (step) => step?.["continue-on-error"] === undefined || step["continue-on-error"] === false,
    ),
    ".github/workflows/verify.yaml: browser evidence steps must not mask failures with continue-on-error",
  );
  requireValue(
    failures,
    evidenceUpload?.with?.["if-no-files-found"] === "error",
    ".github/workflows/verify.yaml: browser evidence upload must fail when required evidence is missing",
  );
  requireValue(
    failures,
    evidenceUpload?.with?.["retention-days"] === 7,
    ".github/workflows/verify.yaml: browser evidence upload must retain artifacts for seven days",
  );
  const evidencePaths = String(evidenceUpload?.with?.path ?? "")
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .filter(Boolean);
  requireValue(
    failures,
    JSON.stringify(evidencePaths) === JSON.stringify(BROWSER_EVIDENCE_OUTPUTS),
    ".github/workflows/verify.yaml: browser evidence upload paths must be the declared report, results, and provenance outputs",
  );
  requireValue(
    failures,
    JSON.stringify(verify.permissions) === JSON.stringify({ contents: "read" }) &&
      browser?.permissions === undefined,
    ".github/workflows/verify.yaml: browser evidence must preserve read-only repository permissions",
  );
  requireValue(
    failures,
    (verify.jobs?.contract?.steps ?? []).some((step) =>
      runsPytest(step, ["tests/test_control_conformance_real.py"]),
    ),
    ".github/workflows/verify.yaml: contract job must run real browser-control conformance",
  );
  requireValue(
    failures,
    (verify.jobs?.unit?.steps ?? []).some((step) =>
      runsPytest(step, ["tests/test_verify_image.py"]),
    ),
    ".github/workflows/verify.yaml: unit job must execute tests/test_verify_image.py",
  );
  requireValue(
    failures,
    (verify.jobs?.contract?.steps ?? []).some(
      (step) =>
        runsShellCommand(step, "pnpm module-conformance:test") &&
        runsShellCommand(step, "pnpm module-conformance:validate"),
    ),
    ".github/workflows/verify.yaml: contract job must validate serialized module conformance independently",
  );

  const wheelCommand = String(
    stepByName(verify.jobs?.python, "Build independent workspace wheels")?.run ?? "",
  );
  const pythonSteps = verify.jobs?.python?.steps ?? [];
  for (const command of ["pnpm ui:format", "pnpm ui:lint", "pnpm ui:test"]) {
    requireValue(
      failures,
      pythonSteps.some((step) => runsShellCommand(step, command)),
      `.github/workflows/verify.yaml: python job must run ${command}`,
    );
  }
  const frontendBuildIndex = pythonSteps.findIndex(
    (step) => step.name === "Build frontend production assets" && step.run === "pnpm ui:build",
  );
  const wheelBuildIndex = pythonSteps.findIndex(
    (step) => step.name === "Build independent workspace wheels",
  );
  requireValue(
    failures,
    frontendBuildIndex >= 0 && wheelBuildIndex > frontendBuildIndex,
    ".github/workflows/verify.yaml: frontend production build must run before workspace wheels",
  );
  for (const distribution of WORKSPACE_DISTRIBUTIONS) {
    requireValue(
      failures,
      new RegExp(`^\\s*uv build .*--package ${distribution}(?:\\s|$)`, "m").test(wheelCommand),
      `.github/workflows/verify.yaml: wheel build is missing ${distribution}`,
    );
  }

  requireValue(
    failures,
    runsPytest(stepByName(verify.jobs?.unit, "Core and unit suites"), [
      "tests/test_prepare_release.py",
    ]),
    ".github/workflows/verify.yaml: unit job must run tests/test_prepare_release.py",
  );

  const listedTestPaths = testPathsFromCommands(verify);
  for (const requiredSuite of ["tests/core", "tests/server", "tests/characterization"]) {
    requireValue(
      failures,
      listedTestPaths.has(requiredSuite),
      `.github/workflows/verify.yaml: required pytest suite ${requiredSuite} is missing`,
    );
  }
  for (const listedPath of listedTestPaths) {
    requireValue(
      failures,
      fs.existsSync(path.join(root, listedPath)),
      `.github/workflows/verify.yaml: listed pytest path does not exist: ${listedPath}`,
    );
  }
  for (const testFile of recursivelyListTests(root)) {
    const relative = path.relative(root, testFile).replaceAll(path.sep, "/");
    const covered = [...listedTestPaths].some(
      (listedPath) => relative === listedPath || relative.startsWith(`${listedPath}/`),
    );
    requireValue(
      failures,
      covered,
      `.github/workflows/verify.yaml: ${relative} is absent from the categorized test jobs`,
    );
  }

  const requiredPytestSteps = [
    [
      "Metadata provider conformance",
      [
        "packages/modules/metadata-manual/tests",
        "packages/modules/metadata-tmdb/tests",
      ],
    ],
    ["Release provider conformance", ["packages/modules/release-prowlarr/tests"]],
    ["Download client conformance", ["packages/modules/download-qbittorrent/tests"]],
    [
      "Manifest and SDK schema drift",
      [
        "packages/module-sdk/tests/test_manifest.py",
        "packages/module-sdk/tests/test_schema_artifacts.py",
      ],
    ],
    [
      "Control and processor OpenAPI drift",
      ["tests/test_control_openapi.py", "tests/test_processor_openapi.py"],
    ],
  ];
  for (const [name, requiredPaths] of requiredPytestSteps) {
    requireValue(
      failures,
      runsPytest(stepByName(verify.jobs?.contract, name), requiredPaths),
      `.github/workflows/verify.yaml: ${name.toLowerCase()} is required with its exact checks`,
    );
  }
  const serialized = stepByName(verify.jobs?.contract, "Serialized module fixture drift");
  requireValue(
    failures,
    runsShellCommand(serialized, "pnpm module-conformance:test") &&
      runsShellCommand(serialized, "pnpm module-conformance:validate"),
    ".github/workflows/verify.yaml: serialized module fixture drift is required with its exact checks",
  );
  const schemaDrift = stepByName(verify.jobs?.contract, "Clean migration and schema drift");
  requireValue(
    failures,
    runsShellCommand(schemaDrift, "uv run python scripts/check_schema_drift.py") &&
      runsPytest(schemaDrift, [
        "tests/test_db.py",
        "tests/architecture/test_clean_core_schema.py",
      ]),
    ".github/workflows/verify.yaml: clean migration and schema drift is required with its exact checks",
  );

  const isolatedUiRunner = readText(
    root,
    "packages/builtin-ui/tests/run_isolated.py",
    failures,
  );
  requireValue(
    failures,
    isolatedUiRunner.includes('sorted(TESTS.rglob("test_*.py"))'),
    "packages/builtin-ui/tests/run_isolated.py: UI isolation runner must discover test files recursively",
  );
}

function validatePublishWorkflows(ci, release, failures) {
  const reusable = "./.github/workflows/verify.yaml";
  requireValue(
    failures,
    Boolean(ci.on?.pull_request) || Object.hasOwn(ci.on ?? {}, "pull_request"),
    ".github/workflows/ci.yaml: pull requests must run verification",
  );
  requireValue(
    failures,
    ci.on?.push?.branches?.includes("main"),
    ".github/workflows/ci.yaml: main pushes must run verification",
  );
  requireValue(
    failures,
    ci.jobs?.verification?.uses === reusable,
    ".github/workflows/ci.yaml: verification job must call the reusable workflow",
  );
  const edge = ci.jobs?.["publish-edge"];
  requireValue(
    failures,
    needs(edge, "verification"),
    ".github/workflows/ci.yaml: edge publish job must need verification",
  );
  requireValue(
    failures,
    normalizedExpression(edge?.if) ===
      "${{ github.event_name == 'push' && github.ref == 'refs/heads/main' }}",
    ".github/workflows/ci.yaml: edge publish condition must be main push only",
  );
  requireValue(
    failures,
    edge?.permissions?.packages === "write",
    ".github/workflows/ci.yaml: only the gated edge publish job needs packages write",
  );
  const edgeBuild = (edge?.steps ?? []).find((step) =>
    String(step.uses ?? "").startsWith("docker/build-push-action@"),
  );
  requireValue(
    failures,
    edgeBuild?.with?.push === true &&
      edgeBuild?.with?.platforms === "linux/amd64,linux/arm64" &&
      edgeBuild?.with?.tags === "ghcr.io/${{ github.repository }}:edge",
    ".github/workflows/ci.yaml: gated edge publish must push the multi-architecture edge tag",
  );

  requireValue(
    failures,
    JSON.stringify(Object.keys(release.on ?? {}).sort()) ===
      JSON.stringify(["release", "workflow_dispatch"]) &&
      JSON.stringify(release.on?.release?.types ?? []) === JSON.stringify(["published"]),
    ".github/workflows/release.yaml: stable publishing must use published releases and one manual entry point",
  );
  const releaseDispatch = release.on?.workflow_dispatch;
  requireValue(
    failures,
    JSON.stringify(Object.keys(releaseDispatch?.inputs ?? {})) === JSON.stringify(["release_tag"]) &&
      releaseDispatch?.inputs?.release_tag?.required === true &&
      releaseDispatch?.inputs?.release_tag?.type === "string",
    ".github/workflows/release.yaml: the manual publication entry point must accept exactly one required tag input",
  );
  requireValue(
    failures,
    release.concurrency?.group === STABLE_PUBLICATION_CONCURRENCY_GROUP,
    ".github/workflows/release.yaml: stable publication concurrency group must serialize every release",
  );
  requireValue(
    failures,
    release.concurrency?.["cancel-in-progress"] === false,
    ".github/workflows/release.yaml: stable publication concurrency must not cancel in-progress releases",
  );
  const stableVerification = release.jobs?.verification;
  const stable = release.jobs?.publish;
  const repair = release.jobs?.repair;
  requireValue(
    failures,
    stableVerification?.uses === reusable,
    ".github/workflows/release.yaml: stable verification must call the reusable workflow",
  );
  requireValue(
    failures,
    normalizedExpression(stableVerification?.if) ===
      "${{ github.event_name == 'workflow_dispatch' || github.event.release.prerelease == false }}",
    ".github/workflows/release.yaml: stable verification must cover the manual entry point and reject prereleases",
  );
  requireValue(
    failures,
    needs(stable, "verification"),
    ".github/workflows/release.yaml: stable publish job must need verification",
  );
  requireValue(
    failures,
    normalizedExpression(stable?.if) === "${{ github.event.release.prerelease == false }}",
    ".github/workflows/release.yaml: stable publish condition must reject prereleases",
  );
  requireValue(
    failures,
    stable?.permissions?.packages === "write" && repair?.permissions?.packages === "write",
    ".github/workflows/release.yaml: only the gated publication jobs need packages write",
  );
  requireValue(
    failures,
    stableVerification?.permissions?.packages !== "write",
    ".github/workflows/release.yaml: stable verification job must not receive package write permission",
  );
  requireValue(
    failures,
    hasExactMapping(stableVerification?.permissions, { contents: "read" }),
    ".github/workflows/release.yaml: stable verification job must use read-only permissions",
  );
  requireValue(
    failures,
    stable?.permissions?.contents === "read",
    ".github/workflows/release.yaml: stable publisher must retain read-only contents access",
  );
  requireValue(
    failures,
    hasExactMapping(stable?.permissions, { contents: "read", packages: "write" }),
    ".github/workflows/release.yaml: stable publisher permissions must be limited to contents read and packages write",
  );
  const stableSteps = stable?.steps ?? [];
  const checkout = stableSteps.find((step) =>
    String(step.uses ?? "").startsWith("actions/checkout@"),
  );
  requireValue(
    failures,
    checkout?.with?.ref === "${{ github.sha }}",
    ".github/workflows/release.yaml: stable publisher checkout must use the release event revision",
  );
  requireValue(
    failures,
    checkout?.with?.["fetch-depth"] === 0,
    ".github/workflows/release.yaml: stable publisher checkout must fetch complete history",
  );
  requireValue(
    failures,
    checkout?.with?.["persist-credentials"] === false,
    ".github/workflows/release.yaml: stable publisher checkout must disable persisted credentials",
  );
  const setupNode = stableSteps.find((step) =>
    String(step.uses ?? "").startsWith("actions/setup-node@"),
  );
  requireValue(
    failures,
    setupNode?.with?.["node-version"] === "24",
    ".github/workflows/release.yaml: stable publisher must use the pinned Node 24 toolchain",
  );
  const publisher = stepByName(stable, RELEASE_PUBLICATION_STEP_NAME);
  requireValue(
    failures,
    publisher?.run === RELEASE_PUBLICATION_COMMAND,
    ".github/workflows/release.yaml: stable publisher must execute scripts/release-publication.mjs",
  );
  requireValue(
    failures,
    publisher?.env?.RELEASE_TAG === "${{ github.event.release.tag_name }}" &&
      publisher?.env?.RELEASE_PRERELEASE === "${{ github.event.release.prerelease }}" &&
      publisher?.env?.RELEASE_DRAFT === "${{ github.event.release.draft }}" &&
      publisher?.env?.RELEASE_URL === "${{ github.event.release.html_url }}" &&
      publisher?.env?.IMAGE_NAME === "ghcr.io/${{ github.repository }}" &&
      publisher?.env?.PUBLICATION_EVIDENCE_PATH === "release-publication-evidence.json",
    ".github/workflows/release.yaml: stable publisher must pass the release identity and evidence path",
  );
  requireValue(
    failures,
    !Object.keys(publisher?.env ?? {}).some((key) =>
      /(token|secret|password|private[_-]?key|credential)/i.test(key),
    ),
    ".github/workflows/release.yaml: stable publisher must not expose credentials to the publication script",
  );
  const obsoletePublisher = stableSteps.some((step) => {
    const usage = String(step.uses ?? "");
    return usage.startsWith("docker/build-push-action@") || usage.startsWith("docker/metadata-action@");
  });
  requireValue(
    failures,
    !obsoletePublisher,
    ".github/workflows/release.yaml: stable publisher must not use a direct Docker build or metadata action",
  );
  const evidenceUpload = stepByName(stable, "Upload stable publication evidence");
  requireValue(
    failures,
    evidenceUpload?.uses === RELEASE_PUBLICATION_EVIDENCE_ACTION,
    ".github/workflows/release.yaml: stable publication evidence must use the approved immutable upload-artifact SHA",
  );
  requireValue(
    failures,
    evidenceUpload?.if === "${{ always() && hashFiles('release-publication-evidence.json') != '' }}",
    ".github/workflows/release.yaml: stable publication evidence upload must run after publication even on failure",
  );
  requireValue(
    failures,
    evidenceUpload?.with?.path === "release-publication-evidence.json" &&
      evidenceUpload?.with?.["if-no-files-found"] === "error" &&
      evidenceUpload?.with?.["retention-days"] === 90,
    ".github/workflows/release.yaml: stable publication evidence must retain the bounded artifact",
  );
  requireValue(
    failures,
    typeof evidenceUpload?.with?.name === "string" &&
      evidenceUpload.with.name.includes("${{ github.run_id }}") &&
      evidenceUpload.with.name.includes("${{ github.run_attempt }}"),
    ".github/workflows/release.yaml: stable publication evidence artifact names must be unique per run attempt",
  );
  const publisherIndex = stableSteps.indexOf(publisher);
  const evidenceIndex = stableSteps.indexOf(evidenceUpload);
  requireValue(
    failures,
    publisherIndex >= 0 && evidenceIndex > publisherIndex,
    ".github/workflows/release.yaml: stable publication evidence must follow the gated publisher",
  );

  // The manual entry point may only complete an existing stable release, using
  // the trusted dispatch revision's publisher while the workspace stays the
  // release commit.
  const repairSteps = repair?.steps ?? [];
  requireValue(
    failures,
    needs(repair, "verification"),
    ".github/workflows/release.yaml: manual publication must need verification",
  );
  requireValue(
    failures,
    normalizedExpression(repair?.if) ===
      "${{ github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main' }}",
    ".github/workflows/release.yaml: manual publication must be main-only",
  );
  requireValue(
    failures,
    hasExactMapping(repair?.permissions, { contents: "read", packages: "write" }),
    ".github/workflows/release.yaml: manual publication permissions must be limited to contents read and packages write",
  );
  const resolveStep = stepByName(repair, "Resolve the requested stable release");
  requireValue(
    failures,
    typeof resolveStep?.run === "string" &&
      resolveStep.run.includes("releases/tags/") &&
      resolveStep.run.includes("GITHUB_OUTPUT") &&
      resolveStep.run.includes("revision=") &&
      resolveStep.run.includes("check-runs") &&
      resolveStep.run.includes("VERSION?ref="),
    ".github/workflows/release.yaml: manual publication must resolve and validate the requested stable release, including its own successful verification, before any registry access",
  );
  const repairCheckouts = repairSteps.filter((step) =>
    String(step.uses ?? "").startsWith("actions/checkout@"),
  );
  const releaseCheckout = repairCheckouts.find((step) => step.with?.path === undefined);
  const trustedCheckout = repairCheckouts.find((step) => step.with?.path !== undefined);
  requireValue(
    failures,
    releaseCheckout?.with?.ref === "${{ steps.resolve.outputs.revision }}" &&
      releaseCheckout?.with?.["persist-credentials"] === false,
    ".github/workflows/release.yaml: manual publication must check out the resolved release commit without persisted credentials",
  );
  requireValue(
    failures,
    trustedCheckout?.with?.ref === "${{ github.sha }}" &&
      typeof trustedCheckout?.with?.path === "string" &&
      trustedCheckout.with.path.length > 0,
    ".github/workflows/release.yaml: manual publication must obtain the publisher from the trusted dispatch revision",
  );
  const repairPublisher = stepByName(repair, RELEASE_PUBLICATION_STEP_NAME);
  requireValue(
    failures,
    typeof repairPublisher?.run === "string" &&
      repairPublisher.run.includes("release-publication.mjs") &&
      repairPublisher.run !== RELEASE_PUBLICATION_COMMAND,
    ".github/workflows/release.yaml: manual publication must run the trusted publisher copy",
  );
  requireValue(
    failures,
    repairPublisher?.env?.GITHUB_SHA === "${{ steps.resolve.outputs.revision }}" &&
      repairPublisher?.env?.RELEASE_TAG === "${{ inputs.release_tag }}" &&
      repairPublisher?.env?.RELEASE_PRERELEASE === "false" &&
      repairPublisher?.env?.RELEASE_DRAFT === "false" &&
      repairPublisher?.env?.IMAGE_NAME === "ghcr.io/${{ github.repository }}" &&
      repairPublisher?.env?.PUBLICATION_EVIDENCE_PATH === "release-publication-evidence.json",
    ".github/workflows/release.yaml: manual publication must pin the resolved stable release identity",
  );
  requireValue(
    failures,
    !Object.keys(repairPublisher?.env ?? {}).some((key) =>
      /(token|secret|password|private[_-]?key|credential)/i.test(key),
    ),
    ".github/workflows/release.yaml: manual publication must not expose credentials to the publication script",
  );
  const repairEvidence = stepByName(repair, "Upload stable publication evidence");
  requireValue(
    failures,
    repairEvidence?.uses === RELEASE_PUBLICATION_EVIDENCE_ACTION &&
      repairEvidence?.if !== undefined &&
      repairEvidence?.with?.path === "release-publication-evidence.json",
    ".github/workflows/release.yaml: manual publication must upload its evidence under the approved action",
  );
}

export function validateDelivery(root = process.cwd(), options = {}) {
  const failures = [];
  validateSecurityExceptions(root, failures, options.currentDate);
  validateCompose(root, failures);
  const ciPath = ".github/workflows/ci.yaml";
  const verifyPath = ".github/workflows/verify.yaml";
  const releasePath = ".github/workflows/release.yaml";
  const ci = loadYaml(root, ciPath, failures);
  const verify = loadYaml(root, verifyPath, failures);
  const release = loadYaml(root, releasePath, failures);
  const verifyText = readText(root, verifyPath, failures);
  validateVerification(root, verify, verifyText, failures);
  validatePublishWorkflows(ci, release, failures);
  validateReleasePreparationWorkflow(root, failures);
  validateActionPins(
    [
      [ciPath, ci],
      [verifyPath, verify],
      [releasePath, release],
      [RELEASE_PREPARATION_WORKFLOW_PATH, loadYaml(root, RELEASE_PREPARATION_WORKFLOW_PATH, failures)],
    ],
    failures,
  );
  validateImage(root, verify, verifyText, failures);
  return failures;
}

const isMain =
  process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) {
  const failures = validateDelivery();
  if (failures.length) {
    console.error(failures.join("\n"));
    process.exit(1);
  }
  console.log("Delivery artifacts satisfy the checked container, workflow, and release contracts.");
}
