import fs from "node:fs";
import process from "node:process";
import YAML from "yaml";

const failures = [];

function loadYaml(path) {
  if (!fs.existsSync(path)) {
    failures.push(`${path}: required delivery artifact is missing`);
    return {};
  }
  try {
    return YAML.parse(fs.readFileSync(path, "utf8")) ?? {};
  } catch (error) {
    failures.push(`${path}: invalid YAML (${error.message})`);
    return {};
  }
}

function requireValue(condition, message) {
  if (!condition) failures.push(message);
}

const compose = loadYaml("compose.example.yaml");
const services = compose.services ?? {};
const serviceNames = Object.keys(services);
requireValue(serviceNames.length === 1, "compose.example.yaml: exactly one service is required");
const service = services[serviceNames[0]] ?? {};
requireValue(
  typeof service.image === "string" && service.image.startsWith("ghcr.io/"),
  "compose.example.yaml: service must use a GHCR image",
);
requireValue(
  (service.ports ?? []).some((port) => String(port).startsWith("127.0.0.1:")),
  "compose.example.yaml: default port must bind to localhost",
);
requireValue(
  (service.volumes ?? []).some((volume) => String(volume).endsWith(":/data")),
  "compose.example.yaml: a named volume must mount at /data",
);
requireValue(Boolean(service.healthcheck?.test), "compose.example.yaml: healthcheck is required");
requireValue(Boolean(service.user), "compose.example.yaml: an explicit non-root user is required");
const composeText = fs.existsSync("compose.example.yaml")
  ? fs.readFileSync("compose.example.yaml", "utf8").toLowerCase()
  : "";
for (const volume of service.volumes ?? []) {
  const target = typeof volume === "string" ? volume.split(":").at(-1) : volume.target;
  requireValue(
    target !== "/downloads" && target !== "/media",
    `compose.example.yaml: forbidden media mount ${target}`,
  );
}
for (const forbidden of ["traefik", "tinyauth", "hametov.uk"]) {
  requireValue(!composeText.includes(forbidden), `compose.example.yaml: forbidden private assumption ${forbidden}`);
}

const dockerfile = fs.existsSync("Dockerfile") ? fs.readFileSync("Dockerfile", "utf8") : "";
requireValue(dockerfile.length > 0, "Dockerfile: required delivery artifact is missing");
requireValue((dockerfile.match(/^FROM /gm) ?? []).length >= 2, "Dockerfile: multi-stage build required");
requireValue(/^USER 10001:10001$/m.test(dockerfile), "Dockerfile: runtime must use UID/GID 10001");
requireValue(
  /ENTRYPOINT \["python", "-m", "media_finder\.runtime"\]/.test(dockerfile),
  "Dockerfile: runtime entrypoint must gate startup",
);

const ci = loadYaml(".github/workflows/ci.yaml");
const ciJobs = ci.jobs ?? {};
const ciText = fs.existsSync(".github/workflows/ci.yaml")
  ? fs.readFileSync(".github/workflows/ci.yaml", "utf8")
  : "";
for (const job of ["documentation", "python", "unit", "integration", "contract", "browser", "image"]) {
  requireValue(Boolean(ciJobs[job]), `.github/workflows/ci.yaml: missing ${job} job`);
}
for (const testFile of fs.readdirSync("tests").filter((name) => /^test_.*\.py$/.test(name))) {
  requireValue(
    ciText.includes(`tests/${testFile}`),
    `.github/workflows/ci.yaml: ${testFile} is absent from the categorized test jobs`,
  );
}
for (const imageAssertion of [
  "docker run --detach",
  "/health/ready",
  "docker exec media-finder-ci id -u",
  "docker exec media-finder-ci id -g",
]) {
  requireValue(
    ciText.includes(imageAssertion),
    `.github/workflows/ci.yaml: production image test is missing ${imageAssertion}`,
  );
}

const release = loadYaml(".github/workflows/release.yaml");
const publish = release.jobs?.publish;
requireValue(Boolean(publish), ".github/workflows/release.yaml: missing publish job");
requireValue(
  release.on?.push?.branches?.includes("main"),
  ".github/workflows/release.yaml: edge publishing must be triggered by main",
);
requireValue(
  release.on?.release?.types?.includes("published"),
  ".github/workflows/release.yaml: stable publishing must use published releases",
);
requireValue(
  String(publish?.if ?? "").includes("prerelease == false"),
  ".github/workflows/release.yaml: prereleases must not enter the stable publish job",
);
const releaseText = fs.existsSync(".github/workflows/release.yaml")
  ? fs.readFileSync(".github/workflows/release.yaml", "utf8")
  : "";
for (const required of [
  "linux/amd64,linux/arm64",
  "type=raw,value=edge",
  "type=semver,pattern=v{{version}}",
  "type=semver,pattern={{major}}.{{minor}}",
  "type=raw,value=latest",
  "flavor: latest=false",
]) {
  requireValue(releaseText.includes(required), `.github/workflows/release.yaml: missing ${required}`);
}
requireValue(
  release.permissions?.packages === "write",
  ".github/workflows/release.yaml: packages write permission is required",
);
requireValue(
  releaseText.includes("Stable release tags must use vX.Y.Z SemVer."),
  ".github/workflows/release.yaml: stable tags must be validated before publishing",
);

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("Delivery artifacts satisfy the checked container, Compose, CI, and release contracts.");
