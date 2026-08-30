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

const VERIFICATION_JOBS = [
  "documentation",
  "python",
  "unit",
  "integration",
  "contract",
  "browser",
  "image",
];

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
          (workflowPath === ".github/workflows/release.yaml" && jobName === "publish");
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
    !Object.hasOwn(release.on ?? {}, "push") &&
      release.on?.release?.types?.includes("published"),
    ".github/workflows/release.yaml: stable publishing must use published releases only",
  );
  const stableVerification = release.jobs?.verification;
  const stable = release.jobs?.publish;
  requireValue(
    failures,
    stableVerification?.uses === reusable,
    ".github/workflows/release.yaml: stable verification must call the reusable workflow",
  );
  requireValue(
    failures,
    normalizedExpression(stableVerification?.if) ===
      "${{ github.event.release.prerelease == false }}",
    ".github/workflows/release.yaml: stable verification must reject prereleases",
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
    stable?.permissions?.packages === "write",
    ".github/workflows/release.yaml: only the gated stable publish job needs packages write",
  );
  const stableBuild = (stable?.steps ?? []).find((step) =>
    String(step.uses ?? "").startsWith("docker/build-push-action@"),
  );
  requireValue(
    failures,
    stableBuild?.with?.push === true &&
      stableBuild?.with?.platforms === "linux/amd64,linux/arm64",
    ".github/workflows/release.yaml: stable publish must push a multi-architecture image",
  );
  const semver = (stable?.steps ?? []).find(
    (step) => step.name === "Validate stable SemVer tag",
  );
  requireValue(
    failures,
    semver?.env?.RELEASE_TAG === "${{ github.event.release.tag_name }}" &&
      String(semver?.run ?? "").includes("Stable release tags must use vX.Y.Z SemVer."),
    ".github/workflows/release.yaml: stable tag must be validated as vX.Y.Z before publishing",
  );

  const metadata = (stable?.steps ?? []).find((step) =>
    String(step.uses ?? "").startsWith("docker/metadata-action@"),
  );
  const stableTags = new Set(
    String(metadata?.with?.tags ?? "")
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean),
  );
  for (const tag of [
    "type=semver,pattern=v{{version}},value=${{ github.event.release.tag_name }}",
    "type=semver,pattern={{major}}.{{minor}},value=${{ github.event.release.tag_name }}",
    "type=raw,value=latest",
  ]) {
    requireValue(
      failures,
      stableTags.has(tag),
      `.github/workflows/release.yaml: stable metadata is missing ${tag}`,
    );
  }
  requireValue(
    failures,
    metadata?.with?.flavor === "latest=false",
    ".github/workflows/release.yaml: automatic latest tagging must be disabled",
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
  validateActionPins(
    [
      [ciPath, ci],
      [verifyPath, verify],
      [releasePath, release],
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
