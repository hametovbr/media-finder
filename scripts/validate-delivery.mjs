import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
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
  } catch (error) {
    failures.push(`${relativePath}: invalid YAML (${error.message})`);
    return {};
  }
}

function needs(job, dependency) {
  const value = job?.needs;
  return value === dependency || (Array.isArray(value) && value.includes(dependency));
}

function normalizedExpression(value) {
  return String(value ?? "").replaceAll(/\s+/g, " ").trim();
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

function validateCompose(root, failures) {
  const compose = loadYaml(root, "compose.example.yaml", failures);
  const services = compose.services ?? {};
  const serviceNames = Object.keys(services);
  requireValue(
    failures,
    serviceNames.length === 1,
    "compose.example.yaml: exactly one service is required",
  );
  const service = services[serviceNames[0]] ?? {};
  requireValue(
    failures,
    typeof service.image === "string" && service.image.startsWith("ghcr.io/"),
    "compose.example.yaml: service must use a GHCR image",
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
  const composeText = readText(root, "compose.example.yaml", failures).toLowerCase();
  for (const forbidden of ["traefik", "tinyauth", "hametov.uk"]) {
    requireValue(
      failures,
      !composeText.includes(forbidden),
      `compose.example.yaml: forbidden private assumption ${forbidden}`,
    );
  }
}

function validateImage(root, verify, failures) {
  const dockerfile = readText(root, "Dockerfile", failures);
  requireValue(
    failures,
    (dockerfile.match(/^FROM /gm) ?? []).length >= 2,
    "Dockerfile: multi-stage build required",
  );
  requireValue(
    failures,
    /^USER 10001:10001$/m.test(dockerfile),
    "Dockerfile: runtime must use UID/GID 10001",
  );
  requireValue(
    failures,
    /ENTRYPOINT \["python", "-m", "media_finder\.runtime"\]/.test(dockerfile),
    "Dockerfile: runtime entrypoint must gate startup",
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
  const smoke = readText(root, "scripts/smoke-container.sh", failures);
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
}

function validateVerification(root, verify, verifyText, failures) {
  requireValue(
    failures,
    Object.hasOwn(verify.on ?? {}, "workflow_call"),
    ".github/workflows/verify.yaml: reusable verification must use workflow_call",
  );
  for (const job of ["documentation", "python", "unit", "integration", "contract", "browser", "image"]) {
    requireValue(
      failures,
      Boolean(verify.jobs?.[job]),
      `.github/workflows/verify.yaml: missing ${job} job`,
    );
  }
  const testsPath = path.join(root, "tests");
  if (fs.existsSync(testsPath)) {
    for (const testFile of fs.readdirSync(testsPath).filter((name) => /^test_.*\.py$/.test(name))) {
      requireValue(
        failures,
        verifyText.includes(`tests/${testFile}`),
        `.github/workflows/verify.yaml: ${testFile} is absent from the categorized test jobs`,
      );
    }
  }
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

export function validateDelivery(root = process.cwd()) {
  const failures = [];
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
  validateImage(root, verify, failures);
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
