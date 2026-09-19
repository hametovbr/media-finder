import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const VERSION_PATTERN = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;
const REVISION_PATTERN = /^[0-9a-f]{40}$/;
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;
const IMAGE_PATTERN = /^ghcr\.io\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const REQUIRED_PLATFORM_NAMES = Object.freeze(["linux/amd64", "linux/arm64"]);
const PUBLICATION_SCHEMA_VERSION = 1;
const COMMAND_TIMEOUT_MILLISECONDS = 30 * 60 * 1000;
const COMMAND_OUTPUT_LIMIT = 4 * 1024 * 1024;
// A blocked publication records what the registry tool said, bounded and stripped
// of anything credential-shaped, so the cause is readable from the workflow log
// and the evidence artifact alone.
const COMMAND_DIAGNOSTIC_LIMIT = 2000;
const CREDENTIAL_DIAGNOSTIC_PATTERN =
  /(authorization|bearer\s|basic\s+[A-Za-z0-9+/=]{8,}|password|passwd|secret|token|private[_-]?key|credential|api[_-]?key)/i;
const publicationQueues = new Map();

const OCI_ATTESTATION_TYPE = "attestation-manifest";
const OCI_VERSION_LABEL = "org.opencontainers.image.version";
const OCI_REVISION_LABEL = "org.opencontainers.image.revision";
const SAFE_SERVER_PATTERN = /^https:\/\/[A-Za-z0-9.-]+$/;
const SAFE_REPOSITORY_PATTERN = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const SAFE_WORKFLOW_URL_PATTERN =
  /^https:\/\/[A-Za-z0-9.-]+\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/actions\/runs\/[1-9]\d*$/;
const SAFE_RELEASE_URL_PATTERN =
  /^https:\/\/[A-Za-z0-9.-]+\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+\/releases\/(?:tag\/v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)|[1-9]\d*)$/;

export class ReleasePublicationError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "ReleasePublicationError";
    this.code = code;
    this.details = details;
  }
}

function publicationError(code, message, details = {}) {
  return new ReleasePublicationError(code, message, details);
}

function parseJson(value) {
  if (value === undefined || value === null || value === "") return undefined;
  if (Buffer.isBuffer(value)) value = value.toString("utf8");
  if (typeof value === "object") return value;
  if (typeof value !== "string") return undefined;
  try {
    return JSON.parse(value);
  } catch {
    return undefined;
  }
}

function outputText(result) {
  if (typeof result === "string") return result;
  if (Buffer.isBuffer(result)) return result.toString("utf8");
  if (result && typeof result.stdout === "string") return result.stdout;
  if (result && Buffer.isBuffer(result.stdout)) return result.stdout.toString("utf8");
  return "";
}

function outputBytes(result) {
  if (Buffer.isBuffer(result)) return result;
  if (result && Buffer.isBuffer(result.stdout)) return result.stdout;
  if (typeof result === "string") return Buffer.from(result, "utf8");
  if (result && typeof result.stdout === "string") return Buffer.from(result.stdout, "utf8");
  return undefined;
}

function validateImage(image) {
  if (typeof image !== "string" || !IMAGE_PATTERN.test(image)) {
    throw publicationError("invalid_image", "The image must be a GHCR owner/repository reference.");
  }
  return image;
}

export function parseStableVersion(value) {
  if (typeof value !== "string") {
    throw publicationError("invalid_version", "Stable releases require a canonical SemVer version.");
  }
  const match = value.match(VERSION_PATTERN);
  if (!match) {
    throw publicationError("invalid_version", "Stable releases require a canonical SemVer version.");
  }
  return {
    text: value,
    major: BigInt(match[1]),
    minor: BigInt(match[2]),
    patch: BigInt(match[3]),
  };
}

function versionText(value) {
  return typeof value === "string" ? parseStableVersion(value).text : value.text;
}

export function compareStableVersions(left, right) {
  const a = typeof left === "string" ? parseStableVersion(left) : left;
  const b = typeof right === "string" ? parseStableVersion(right) : right;
  for (const field of ["major", "minor", "patch"]) {
    if (a[field] < b[field]) return -1;
    if (a[field] > b[field]) return 1;
  }
  return 0;
}

function validateRevision(value) {
  if (typeof value !== "string" || !REVISION_PATTERN.test(value)) {
    throw publicationError("invalid_revision", "The source revision must be a 40-character Git SHA.");
  }
  return value;
}

function validateDigest(value) {
  return typeof value === "string" && DIGEST_PATTERN.test(value);
}

function releaseTagForVersion(version) {
  return `v${versionText(version)}`;
}

export function expectedImageTags(image, version) {
  const validatedImage = validateImage(image);
  const parsedVersion = typeof version === "string" ? parseStableVersion(version) : version;
  const text = versionText(parsedVersion);
  const immutable = `${validatedImage}:${releaseTagForVersion(parsedVersion)}`;
  const minor = `${validatedImage}:${parsedVersion.major.toString()}.${parsedVersion.minor.toString()}`;
  const latest = `${validatedImage}:latest`;
  return Object.freeze({
    immutable,
    full: immutable,
    minor,
    latest,
    names: Object.freeze({
      immutable: `v${text}`,
      full: `v${text}`,
      minor: `${parsedVersion.major.toString()}.${parsedVersion.minor.toString()}`,
      latest: "latest",
    }),
  });
}

function platformName(platform) {
  if (!platform || platform.os !== "linux") return undefined;
  if (platform.architecture === "amd64") return "linux/amd64";
  if (platform.architecture === "arm64") return "linux/arm64";
  return undefined;
}

function isAttestation(descriptor) {
  return descriptor?.annotations?.["vnd.docker.reference.type"] === OCI_ATTESTATION_TYPE;
}

function safeDescriptor(descriptor) {
  const result = {};
  if (typeof descriptor?.mediaType === "string") result.mediaType = descriptor.mediaType;
  if (validateDigest(descriptor?.digest)) result.digest = descriptor.digest;
  if (Number.isSafeInteger(descriptor?.size)) result.size = descriptor.size;
  if (descriptor?.platform && typeof descriptor.platform === "object") {
    const platform = {};
    if (typeof descriptor.platform.os === "string") platform.os = descriptor.platform.os;
    if (typeof descriptor.platform.architecture === "string") {
      platform.architecture = descriptor.platform.architecture;
    }
    if (typeof descriptor.platform.variant === "string") platform.variant = descriptor.platform.variant;
    result.platform = platform;
  }
  if (descriptor?.annotations && typeof descriptor.annotations === "object") {
    const annotations = {};
    if (typeof descriptor.annotations["vnd.docker.reference.type"] === "string") {
      annotations["vnd.docker.reference.type"] = descriptor.annotations["vnd.docker.reference.type"];
    }
    if (typeof descriptor.annotations["vnd.docker.reference.digest"] === "string") {
      annotations["vnd.docker.reference.digest"] = descriptor.annotations["vnd.docker.reference.digest"];
    }
    if (Object.keys(annotations).length) result.annotations = annotations;
  }
  return result;
}

function imageForPlatform(images, name) {
  if (!images || typeof images !== "object" || Array.isArray(images)) return undefined;
  return images[name];
}

function labelsForImage(image) {
  const labels = image?.config?.Labels;
  return labels && typeof labels === "object" ? labels : {};
}

function labelValue(image, key) {
  const labels = labelsForImage(image);
  return typeof labels[key] === "string" ? labels[key] : undefined;
}

function rawBytes(value) {
  if (Buffer.isBuffer(value)) return value;
  if (typeof value === "string") return Buffer.from(value, "utf8");
  return undefined;
}

function rawManifestDigest(value) {
  const bytes = rawBytes(value);
  if (!bytes || bytes.length === 0) return undefined;
  return `sha256:${createHash("sha256").update(bytes).digest("hex")}`;
}

function comparableManifest(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const { digest: _digest, size: _size, ...withoutRegistryIdentity } = value;
  return withoutRegistryIdentity;
}

function canonicalJson(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  return JSON.stringify(value);
}

/**
 * Convert the concrete Docker adapter shape into the small evidence shape used
 * by publication decisions. `raw` is the exact `--raw` byte stream and
 * `formatted` is the parsed `--format "{{json .}}"` object collected by the
 * adapter after it re-inspected the derived digest reference.
 */
export function parseRegistryInspection(value, options = {}) {
  if (value === undefined || value === null) return undefined;
  const container = parseJson(value);
  if (!container || typeof container !== "object" || Array.isArray(container)) return undefined;
  const rawValue = container.raw;
  const formatted = parseJson(container.formatted);
  const raw = parseJson(rawValue);
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return undefined;
  if (!formatted || typeof formatted !== "object" || Array.isArray(formatted)) return undefined;
  const formattedManifest = formatted.manifest;
  if (!formattedManifest || typeof formattedManifest !== "object" || Array.isArray(formattedManifest)) {
    return undefined;
  }
  const digest = rawManifestDigest(rawValue);
  if (!validateDigest(digest) || !validateDigest(formattedManifest.digest)) return undefined;
  if (digest !== formattedManifest.digest) {
    throw publicationError(
      "digest_mismatch",
      `Registry raw and formatted manifests disagree for ${options.reference ?? "the image"}.`,
      { reference: options.reference, rawDigest: digest, formattedDigest: formattedManifest.digest },
    );
  }
  if (canonicalJson(comparableManifest(raw)) !== canonicalJson(comparableManifest(formattedManifest))) {
    throw publicationError(
      "inspection_mismatch",
      `Registry raw and formatted index contents disagree for ${options.reference ?? "the image"}.`,
      { reference: options.reference, digest },
    );
  }
  const descriptors = Array.isArray(raw.manifests) ? raw.manifests : [];
  const images = formatted.image;
  const runtimeDescriptors = [];
  const allDescriptors = [];
  for (const candidate of descriptors) {
    if (!candidate || typeof candidate !== "object") continue;
    const descriptor = safeDescriptor(candidate);
    allDescriptors.push(descriptor);
    if (isAttestation(candidate)) continue;
    const name = platformName(candidate.platform);
    if (!name) continue;
    const image = imageForPlatform(images, name);
    runtimeDescriptors.push({
      name,
      digest: descriptor.digest,
      mediaType: descriptor.mediaType,
      version: labelValue(image, OCI_VERSION_LABEL),
      sourceRevision: labelValue(image, OCI_REVISION_LABEL),
    });
  }
  const index = {
    ...(Number.isInteger(raw.schemaVersion) ? { schemaVersion: raw.schemaVersion } : {}),
    ...(typeof raw.mediaType === "string" ? { mediaType: raw.mediaType } : {}),
    ...(digest ? { digest } : {}),
    manifests: allDescriptors,
  };
  const platforms = runtimeDescriptors
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name));
  const sourceRevisions = Object.fromEntries(
    platforms.map(({ name, sourceRevision }) => [name, sourceRevision ?? null]),
  );
  const versions = Object.fromEntries(
    platforms.map(({ name, version }) => [name, version ?? null]),
  );
  return {
    reference: options.reference,
    digest,
    mediaType: typeof raw.mediaType === "string" ? raw.mediaType : formattedManifest.mediaType,
    index,
    platforms,
    sourceRevisions,
    versions,
  };
}

function requiredPlatforms(inspection) {
  const byName = new Map();
  for (const platform of inspection?.platforms ?? []) {
    if (!REQUIRED_PLATFORM_NAMES.includes(platform.name)) continue;
    if (!byName.has(platform.name)) byName.set(platform.name, []);
    byName.get(platform.name).push(platform);
  }
  return byName;
}

function inspectionVersion(inspection) {
  const byName = requiredPlatforms(inspection);
  if (byName.size !== REQUIRED_PLATFORM_NAMES.length) return undefined;
  const values = [];
  for (const name of REQUIRED_PLATFORM_NAMES) {
    const entries = byName.get(name);
    if (entries.length !== 1 || typeof entries[0].version !== "string") return undefined;
    try {
      values.push(parseStableVersion(entries[0].version).text);
    } catch {
      return undefined;
    }
  }
  return values.every((value) => value === values[0]) ? values[0] : undefined;
}

function inspectionHasRuntimeShape(inspection) {
  if (!validateDigest(inspection?.digest)) return false;
  const byName = requiredPlatforms(inspection);
  if (byName.size !== REQUIRED_PLATFORM_NAMES.length) return false;
  return REQUIRED_PLATFORM_NAMES.every((name) => {
    const entries = byName.get(name);
    return entries.length === 1 && validateDigest(entries[0].digest);
  });
}

/** Verify the immutable index and per-architecture OCI labels. */
export function verifyRegistryInspection(
  inspection,
  { reference = inspection?.reference, version, revision, expectedDigest } = {},
) {
  if (!inspection || !inspectionHasRuntimeShape(inspection)) {
    if (
      inspection &&
      requiredPlatforms(inspection).size < REQUIRED_PLATFORM_NAMES.length
    ) {
      throw publicationError(
        "missing_architecture",
        `Registry manifest is missing a required runtime platform for ${reference ?? "the image"}.`,
        { reference },
      );
    }
    throw publicationError(
      "invalid_manifest",
      `Registry manifest is malformed or unverifiable for ${reference ?? "the image"}.`,
      { reference },
    );
  }
  if (expectedDigest && inspection.digest !== expectedDigest) {
    throw publicationError(
      "immutable_tag_reuse",
      `Immutable image identity differs for ${reference ?? "the image"}.`,
      { reference, expectedDigest, actualDigest: inspection.digest },
    );
  }
  const expectedVersion = versionText(version);
  for (const name of REQUIRED_PLATFORM_NAMES) {
    const platform = requiredPlatforms(inspection).get(name)[0];
    if (platform.sourceRevision !== revision) {
      throw publicationError(
        "digest_revision_mismatch",
        `Registry source revision mismatch for ${reference ?? "the image"}.`,
        { reference, platform: name },
      );
    }
    if (platform.version !== expectedVersion) {
      throw publicationError(
        "tag_version_mismatch",
        `Registry tag/version mismatch for ${reference ?? "the image"}.`,
        { reference, platform: name, expectedVersion, actualVersion: platform.version },
      );
    }
  }
  return inspection;
}

function verifyMovingShape(inspection, reference) {
  if (!inspectionHasRuntimeShape(inspection) || !inspectionVersion(inspection)) {
    throw publicationError(
      "moving_tag_conflict",
      `Moving tag ${reference} has unverifiable image metadata.`,
      { reference },
    );
  }
  return inspectionVersion(inspection);
}

function sanitizeCommandDiagnostic(error) {
  const parts = [];
  for (const value of [error?.stderr, error?.stdout]) {
    const text = Buffer.isBuffer(value) ? value.toString("utf8") : value;
    if (typeof text === "string" && text.trim() !== "") parts.push(text);
  }
  // A timeout, an output-limit guard or a spawn failure rejects without captured
  // output, and the error's own identity is then the only cause available.
  if (parts.length === 0) {
    const fallback = [error?.code, error?.message]
      .filter((value) => typeof value === "string" && value.trim() !== "")
      .join(": ");
    if (fallback === "" || CREDENTIAL_DIAGNOSTIC_PATTERN.test(fallback)) return undefined;
    return fallback.slice(0, COMMAND_DIAGNOSTIC_LIMIT);
  }
  const lines = parts
    .join("\n")
    .split(/\r?\n/)
    .map((line) => line.replace(/\/\/[^/@\s]*@/g, "//"))
    // Pre-signed registry and blob URLs carry their credential in the query
    // string or fragment, so neither may survive into a published artifact.
    .map((line) => line.replace(/https?:\/\/[^\s?#]*[?#][^\s]*/gi, (match) => `${match.split(/[?#]/)[0]}?<redacted>`))
    .map((line) => line.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, ""))
    .filter((line) => line.trim() !== "")
    .filter((line) => !CREDENTIAL_DIAGNOSTIC_PATTERN.test(line));
  if (lines.length === 0) return undefined;
  const bounded = lines.join(" | ").slice(0, COMMAND_DIAGNOSTIC_LIMIT);
  return bounded === "" ? undefined : bounded;
}

function commandFailure(code, command, error) {
  const diagnostic = sanitizeCommandDiagnostic(error);
  const details = {
    command,
    status: Number.isInteger(error?.status) ? error.status : undefined,
    ...(diagnostic === undefined ? {} : { diagnostic }),
  };
  return publicationError(code, `Docker registry command failed: ${command}.`, details);
}

function commandOutput(result) {
  return outputText(result);
}

function isAuthoritativeManifestAbsenceError(error) {
  const status = error?.status;
  // runCommand reports the completed subprocess exit code. A missing status or
  // a signal termination cannot establish registry absence, and status 404 is
  // reserved for HTTP-shaped wrapper errors rather than a process exit.
  if (!Number.isInteger(status) || status <= 0 || status > 255 || status === 404) return false;
  if (error?.signal !== null && error?.signal !== undefined) return false;
  const stderr = Buffer.isBuffer(error?.stderr) ? error.stderr.toString("utf8") : error?.stderr;
  if (typeof stderr !== "string") return false;
  const diagnostic = `${stderr ?? ""} ${error?.message ?? ""}`.toLowerCase();
  // The registry CLI reports a missing tag on its own line as
  // `ERROR: <reference>: not found`; the daemon's `HTTP 404 not found` and a
  // `network not found` message must not be read the same way, so the observed
  // form is anchored to that line shape rather than to the words alone.
  const manifestMissing =
    /\b(?:manifest unknown|name unknown|no such manifest)\b/.test(diagnostic) ||
    /^\s*error:\s+.+:\s+not found\s*$/m.test(diagnostic);
  if (!manifestMissing) return false;
  return !/(?:unauthori[sz]ed|authentication|access denied|permission denied|forbidden|timed? out|timeout|network|connection|dns|tls|proxy|gateway|service unavailable)/.test(
    diagnostic,
  );
}

function runCommand(command, args, options = {}) {
  const cwd = options.cwd ?? process.cwd();
  const environment = options.env ?? process.env;
  const timeout = options.timeout ?? COMMAND_TIMEOUT_MILLISECONDS;
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: environment,
      shell: false,
      stdio: ["ignore", "pipe", "pipe"],
    });
    const stdout = [];
    const stderr = [];
    let outputBytes = 0;
    let settled = false;
    const finishError = (error) => {
      if (settled) return;
      settled = true;
      reject(error);
    };
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      finishError(Object.assign(new Error("command timeout"), { code: "ETIMEDOUT" }));
    }, timeout);
    const read = (target, chunk) => {
      outputBytes += chunk.length;
      if (outputBytes > COMMAND_OUTPUT_LIMIT) {
        child.kill("SIGTERM");
        finishError(Object.assign(new Error("command output limit"), { code: "OUTPUT_LIMIT" }));
        return;
      }
      target.push(chunk);
    };
    child.stdout.on("data", (chunk) => read(stdout, chunk));
    child.stderr.on("data", (chunk) => read(stderr, chunk));
    child.on("error", (error) => {
      clearTimeout(timer);
      finishError(error);
    });
    child.on("close", (status, signal) => {
      clearTimeout(timer);
      if (settled) return;
      settled = true;
      const result = {
        status,
        signal,
        stdout: Buffer.concat(stdout),
        stderr: Buffer.concat(stderr),
      };
      if (status !== 0) {
        reject(Object.assign(new Error("command failed"), result));
      } else {
        resolve(result);
      }
    });
  });
}

/** Buildx/registry adapter used by the production CLI and fixture tests. */
export function createDockerRegistryClient({ cwd = process.cwd(), command = runCommand } = {}) {
  return {
    async inspect(reference) {
      let rawResult;
      try {
        rawResult = await command("docker", ["buildx", "imagetools", "inspect", "--raw", reference], {
          cwd,
        });
      } catch (error) {
        if (isAuthoritativeManifestAbsenceError(error)) return undefined;
        throw commandFailure("registry_inspection_failed", "docker buildx imagetools inspect", error);
      }
      const rawValue = outputBytes(rawResult);
      const raw = parseJson(rawValue);
      const digest = rawManifestDigest(rawValue);
      if (
        !raw ||
        typeof raw !== "object" ||
        Array.isArray(raw) ||
        !Array.isArray(raw.manifests) ||
        !validateDigest(digest)
      ) {
        throw publicationError(
          "invalid_manifest",
          `Registry raw inspection was not a valid JSON manifest for ${reference}.`,
          { reference },
        );
      }
      const digestReference = `${reference}@${digest}`;
      let formattedResult;
      try {
        formattedResult = await command(
          "docker",
          ["buildx", "imagetools", "inspect", "--format", "{{json .}}", digestReference],
          { cwd },
        );
      } catch (error) {
        throw commandFailure("registry_inspection_failed", "docker buildx imagetools inspect", error);
      }
      const formatted = parseJson(commandOutput(formattedResult));
      if (!formatted || typeof formatted !== "object" || Array.isArray(formatted)) {
        throw publicationError(
          "invalid_manifest",
          `Registry inspection was not valid JSON for ${reference}.`,
          { reference },
        );
      }
      const formattedDigest = formatted.manifest?.digest;
      if (!formatted.manifest || typeof formatted.manifest !== "object" || !validateDigest(formattedDigest)) {
        throw publicationError(
          "invalid_manifest",
          `Registry formatted inspection was missing manifest metadata for ${reference}.`,
          { reference },
        );
      }
      if (formattedDigest !== digest) {
        throw publicationError(
          "digest_mismatch",
          `Registry digest inspection did not match the raw manifest for ${reference}.`,
          { reference, rawDigest: digest, formattedDigest },
        );
      }
      const value = { raw: rawValue, formatted };
      if (!parseRegistryInspection(value, { reference })) {
        throw publicationError(
          "invalid_manifest",
          `Registry inspection was missing the documented manifest shape for ${reference}.`,
          { reference },
        );
      }
      return value;
    },

    async build({ ref, version, revision }) {
      const args = [
        "buildx",
        "build",
        "--platform",
        REQUIRED_PLATFORM_NAMES.join(","),
        "--tag",
        ref,
        "--label",
        `${OCI_VERSION_LABEL}=${version}`,
        "--label",
        `${OCI_REVISION_LABEL}=${revision}`,
        "--provenance=mode=max",
        "--push",
        ".",
      ];
      try {
        await command("docker", args, { cwd });
      } catch (error) {
        throw commandFailure("build_failed", "docker buildx build", error);
      }
    },

    async retag({ source, destination }) {
      try {
        await command(
          "docker",
          ["buildx", "imagetools", "create", "--tag", destination, source],
          { cwd },
        );
      } catch (error) {
        throw commandFailure("retag_failed", "docker buildx imagetools create", error);
      }
    },
  };
}

function assertRegistry(registry) {
  for (const method of ["inspect", "build", "retag"]) {
    if (!registry || typeof registry[method] !== "function") {
      throw publicationError("invalid_registry_adapter", `Registry adapter must provide ${method}().`);
    }
  }
}

async function inspectRegistry(registry, reference, { allowAbsent = false } = {}) {
  try {
    const value = await registry.inspect(reference);
    if (value === undefined || value === null) {
      if (allowAbsent) return undefined;
      throw publicationError(
        "registry_inspection_ambiguous",
        `Registry absence could not be authenticated for ${reference}.`,
        { reference },
      );
    }
    const inspection = parseRegistryInspection(value, { reference });
    if (!inspection) {
      throw publicationError(
        "invalid_manifest",
        `Registry inspection was malformed for ${reference}.`,
        { reference },
      );
    }
    return inspection;
  } catch (error) {
    if (error instanceof ReleasePublicationError) throw error;
    throw publicationError(
      "registry_inspection_failed",
      `Unable to inspect registry image ${reference}.`,
      { reference },
    );
  }
}

async function buildImage(registry, input) {
  try {
    await registry.build(input);
  } catch (error) {
    if (error instanceof ReleasePublicationError) throw error;
    throw publicationError("build_failed", "Stable image build failed.");
  }
}

async function retagImage(registry, input) {
  try {
    await registry.retag(input);
  } catch (error) {
    if (error instanceof ReleasePublicationError) throw error;
    throw publicationError("retag_failed", "Stable image tag repair failed.");
  }
}

async function planMovingTags(registry, tags, version, revision, expectedDigest) {
  const plans = [];
  let adoptedDigest;
  let adoptedReference;
  for (const key of ["minor", "latest"]) {
    const reference = tags[key];
    const inspection = await inspectRegistry(registry, reference, { allowAbsent: true });
    if (!inspection) {
      plans.push({ key, reference, action: "retag" });
      continue;
    }
    const currentVersion = verifyMovingShape(inspection, reference);
    const ordering = compareStableVersions(currentVersion, version);
    if (ordering > 0) {
      throw publicationError(
        "moving_tag_regression",
        `Moving tag ${reference} points to a newer release; refusing regression.`,
        { reference, currentVersion, requestedVersion: version },
      );
    }
    if (ordering === 0) {
      if (expectedDigest && inspection.digest === expectedDigest) {
        verifyRegistryInspection(inspection, {
          reference,
          version,
          revision,
          expectedDigest,
        });
        plans.push({ key, reference, action: "reuse", inspection });
        continue;
      }
      if (!expectedDigest) {
        try {
          verifyRegistryInspection(inspection, { reference, version, revision });
        } catch {
          throw publicationError(
            "moving_tag_conflict",
            `Moving tag ${reference} conflicts with the requested release.`,
            { reference, currentVersion: version },
          );
        }
        if (adoptedDigest && adoptedDigest !== inspection.digest) {
          throw publicationError(
            "moving_tag_conflict",
            `Moving tags for ${version} resolve to different immutable digests.`,
            { reference },
          );
        }
        adoptedDigest = inspection.digest;
        adoptedReference = reference;
        plans.push({ key, reference, action: "retag", inspection });
        continue;
      }
      throw publicationError(
        "moving_tag_conflict",
        `Moving tag ${reference} conflicts with the immutable release digest.`,
        { reference, expectedDigest, actualDigest: inspection.digest },
      );
    }
    plans.push({ key, reference, action: "retag", inspection });
  }
  return { plans, adoptedDigest, adoptedReference };
}

async function publishStableImageOnce(options) {
  const progress = {
    image: options?.image,
    version: options?.version,
    releaseTag: options?.releaseTag,
    sourceRevision: options?.revision,
    workflowURL: options?.workflowURL,
    releaseURL: options?.releaseURL,
    actualTags: [],
  };
  try {
    return await publishStableImageUnchecked(options, progress);
  } catch (error) {
    if (error instanceof ReleasePublicationError) {
      error.details = {
        ...error.details,
        publication: {
          image: progress.image,
          version: progress.version,
          releaseTag: progress.releaseTag,
          immutableReference: progress.knownImmutableReference,
          sourceRevision: progress.sourceRevision,
          digest: progress.knownDigest,
          index: progress.knownIndex,
          platforms: progress.knownPlatforms,
          actualTags: progress.actualTags,
          recovery: progress.recovery,
          workflowURL: progress.workflowURL,
          releaseURL: progress.releaseURL,
        },
      };
    }
    throw error;
  }
}

async function publishStableImageUnchecked({
  image,
  releaseTag,
  version,
  revision,
  registry,
  workflowURL,
  releaseURL,
  allowInitialImmutableAbsence = true,
}, progress) {
  const parsedVersion = parseStableVersion(version);
  const normalizedVersion = parsedVersion.text;
  const normalizedRevision = validateRevision(revision);
  if (releaseTag !== releaseTagForVersion(parsedVersion)) {
    throw publicationError(
      "tag_version_mismatch",
      "The release tag must equal v<checked-out VERSION>.",
      { releaseTag, version: normalizedVersion },
    );
  }
  validatePublicationURLs(workflowURL, releaseURL, releaseTag, image);
  assertRegistry(registry);
  const tags = expectedImageTags(image, parsedVersion);
  progress.image = image;
  progress.version = normalizedVersion;
  progress.releaseTag = releaseTag;
  progress.sourceRevision = normalizedRevision;
  progress.knownImmutableReference = tags.immutable;
  const immutableInspection = await inspectRegistry(registry, tags.immutable, { allowAbsent: true });
  let immutableDigest;
  let built = false;
  let repairedImmutable = false;
  if (immutableInspection) {
    verifyRegistryInspection(immutableInspection, {
      reference: tags.immutable,
      version: normalizedVersion,
      revision: normalizedRevision,
    });
    immutableDigest = immutableInspection.digest;
    rememberKnownInspection(progress, immutableInspection);
  }

  // Preflight both moving pointers before building or retagging anything. This
  // prevents an older rerun from updating one pointer before discovering that
  // the other pointer is newer.
  const initialPlan = await planMovingTags(
    registry,
    tags,
    normalizedVersion,
    normalizedRevision,
    immutableDigest,
  );
  if (!immutableDigest && initialPlan.adoptedDigest) {
    immutableDigest = initialPlan.adoptedDigest;
    const adoptedPlan = initialPlan.plans.find(
      ({ inspection }) => inspection?.digest === immutableDigest,
    );
    rememberKnownInspection(progress, adoptedPlan?.inspection);
  }
  if (!immutableDigest && !allowInitialImmutableAbsence) {
    throw publicationError(
      "registry_inspection_ambiguous",
      `The immutable image identity is absent or unverifiable for ${tags.immutable}; refusing to rebuild it.`,
      { reference: tags.immutable },
    );
  }
  if (!immutableDigest) {
    try {
      await buildImage(registry, {
        ref: tags.immutable,
        image,
        version: normalizedVersion,
        revision: normalizedRevision,
      });
    } catch (error) {
      // A registry push can succeed before the client reports a timeout. Read
      // the immutable tag once so the failure evidence can carry its verified
      // identity and the next run can reconcile it without rebuilding.
      try {
        const recoveredInspection = await inspectRegistry(registry, tags.immutable);
        if (recoveredInspection) {
          verifyRegistryInspection(recoveredInspection, {
            reference: tags.immutable,
            version: normalizedVersion,
            revision: normalizedRevision,
          });
          rememberKnownInspection(progress, recoveredInspection);
        }
      } catch (recoveryError) {
        progress.recovery = recoveryError?.code === "registry_inspection_ambiguous"
          ? "ambiguous"
          : "unverified";
        // Preserve the original build failure; an unverifiable tag is not proof
        // that the push completed.
      }
      throw error;
    }
    built = true;
    let builtInspection;
    try {
      builtInspection = await inspectRegistry(registry, tags.immutable);
      verifyRegistryInspection(builtInspection, {
        reference: tags.immutable,
        version: normalizedVersion,
        revision: normalizedRevision,
      });
    } catch (error) {
      progress.recovery = error?.code === "registry_inspection_ambiguous" ? "ambiguous" : "unverified";
      throw error;
    }
    immutableDigest = builtInspection.digest;
    rememberKnownInspection(progress, builtInspection);
  } else if (!immutableInspection) {
    await retagImage(registry, {
      source: `${initialPlan.adoptedReference}@${immutableDigest}`,
      destination: tags.immutable,
    });
    let adoptedInspection;
    try {
      adoptedInspection = await inspectRegistry(registry, tags.immutable);
      verifyRegistryInspection(adoptedInspection, {
        reference: tags.immutable,
        version: normalizedVersion,
        revision: normalizedRevision,
        expectedDigest: immutableDigest,
      });
    } catch (error) {
      progress.recovery = error?.code === "registry_inspection_ambiguous" ? "ambiguous" : "unverified";
      throw error;
    }
    repairedImmutable = true;
    rememberKnownInspection(progress, adoptedInspection);
  }

  const finalPlan = await planMovingTags(
    registry,
    tags,
    normalizedVersion,
    normalizedRevision,
    immutableDigest,
  );
  const repaired = [];
  for (const plan of finalPlan.plans) {
    if (plan.action !== "retag") continue;
    await retagImage(registry, {
      source: `${tags.immutable}@${immutableDigest}`,
      destination: plan.reference,
    });
    repaired.push(plan.key);
  }

  const actualTags = [];
  let immutableEvidence;
  for (const key of ["immutable", "minor", "latest"]) {
    const reference = tags[key];
    let inspection;
    try {
      inspection = await inspectRegistry(registry, reference);
      verifyRegistryInspection(inspection, {
        reference,
        version: normalizedVersion,
        revision: normalizedRevision,
        expectedDigest: immutableDigest,
      });
    } catch (error) {
      progress.recovery = error?.code === "registry_inspection_ambiguous" ? "ambiguous" : "unverified";
      throw error;
    }
    if (key === "immutable") immutableEvidence = inspection;
    const actualTag = {
      name: tags.names[key],
      tag: tags.names[key],
      reference,
      digest: inspection.digest,
      index: inspection.index,
      platforms: inspection.platforms,
      sourceRevision: normalizedRevision,
    };
    actualTags.push(actualTag);
    progress.actualTags.push(actualTag);
  }
  const state = built ? "published" : repairedImmutable || repaired.length ? "repaired" : "reused";
  return {
    schemaVersion: PUBLICATION_SCHEMA_VERSION,
    operation: "stable-image-publication",
    state,
    image,
    version: normalizedVersion,
    releaseTag,
    sourceRevision: normalizedRevision,
    digest: immutableDigest,
    index: immutableEvidence.index,
    platforms: REQUIRED_PLATFORM_NAMES.slice(),
    actualTags,
    workflowURL,
    releaseURL,
    repairedTags: repaired,
  };
}

/**
 * Publish one stable image identity. Calls for the same GHCR image are queued
 * in-process; the workflow adds repository-wide Actions concurrency as the
 * cross-run lock.
 */
export function publishStableImage(options) {
  const image = validateImage(options?.image);
  const version = parseStableVersion(options?.version).text;
  const key = `stable-image:${image}`;
  const previous = publicationQueues.get(key) ?? Promise.resolve();
  const current = previous.catch(() => undefined).then(() =>
    publishStableImageOnce({ ...options, image, version }),
  );
  // Keep the queue promise fulfilled so a failed publication cannot surface as
  // an unhandled rejection in the next caller. The caller still receives the
  // original `current` promise and its typed failure.
  const tracked = current.then(
    () => undefined,
    () => undefined,
  );
  tracked.then(() => {
    if (publicationQueues.get(key) === tracked) publicationQueues.delete(key);
  });
  publicationQueues.set(key, tracked);
  return current;
}

async function gitOutput(root, args) {
  try {
    return commandOutput(await runCommand("git", args, { cwd: root })).trim();
  } catch {
    throw publicationError("checkout_verification_failed", "Unable to verify the checked-out release revision.");
  }
}

export async function readReleaseContext(root, releaseTag, expectedRevision) {
  const parsedTag = typeof releaseTag === "string" ? releaseTag.match(/^v(.*)$/) : undefined;
  if (!parsedTag) {
    throw publicationError("invalid_version", "Stable releases require a canonical vX.Y.Z tag.");
  }
  const version = parseStableVersion(parsedTag[1]).text;
  const versionPath = path.join(root, "VERSION");
  let versionContents;
  try {
    versionContents = fs.readFileSync(versionPath, "utf8");
  } catch {
    throw publicationError("checkout_verification_failed", "The checked-out VERSION file is unavailable.");
  }
  if (!/^\S+\n?$/.test(versionContents)) {
    throw publicationError("checkout_verification_failed", "The checked-out VERSION file is malformed.");
  }
  const checkedOutVersion = versionContents.trim();
  if (checkedOutVersion !== version) {
    throw publicationError(
      "tag_version_mismatch",
      "The release tag does not equal the checked-out VERSION.",
      { releaseTag, checkedOutVersion, version },
    );
  }
  const revision = validateRevision(await gitOutput(root, ["rev-parse", "HEAD"]));
  if (expectedRevision !== undefined && revision !== validateRevision(expectedRevision)) {
    throw publicationError(
      "checkout_revision_mismatch",
      "The checked-out revision does not match the release event revision.",
      { releaseTag },
    );
  }
  const tagRevision = validateRevision(await gitOutput(root, ["rev-parse", `refs/tags/${releaseTag}^{commit}`]));
  if (revision !== tagRevision) {
    throw publicationError(
      "checkout_revision_mismatch",
      "The checked-out revision does not match the stable release tag target.",
      { releaseTag },
    );
  }
  return { version, revision, releaseTag };
}

function safeWorkflowURL(environment) {
  const server = environment.GITHUB_SERVER_URL ?? "https://github.com";
  const repository = environment.GITHUB_REPOSITORY;
  const runID = environment.GITHUB_RUN_ID;
  if (
    typeof server !== "string" ||
    !SAFE_SERVER_PATTERN.test(server) ||
    typeof repository !== "string" ||
    !SAFE_REPOSITORY_PATTERN.test(repository) ||
    !/^[1-9]\d*$/.test(String(runID ?? ""))
  ) {
    return undefined;
  }
  return `${server}/${repository}/actions/runs/${runID}`;
}

function safeReleaseURL(environment, releaseTag) {
  const server = environment.GITHUB_SERVER_URL ?? "https://github.com";
  const repository = environment.GITHUB_REPOSITORY;
  const value = environment.RELEASE_URL;
  if (
    typeof server !== "string" ||
    !SAFE_SERVER_PATTERN.test(server) ||
    typeof repository !== "string" ||
    !SAFE_REPOSITORY_PATTERN.test(repository) ||
    typeof value !== "string"
  ) {
    return undefined;
  }
  const releasePrefix = `${server}/${repository}/releases/`;
  if (
    value === `${releasePrefix}tag/${releaseTag}` ||
    (value.startsWith(releasePrefix) && /^[1-9]\d*$/.test(value.slice(releasePrefix.length)))
  ) {
    return value;
  }
  return undefined;
}

function validatePublicationURLs(workflowURL, releaseURL, releaseTag, image) {
  if (typeof workflowURL !== "string" || !SAFE_WORKFLOW_URL_PATTERN.test(workflowURL)) {
    throw publicationError(
      "invalid_workflow_url",
      "Stable publication requires a validated workflow URL.",
    );
  }
  const repository = typeof image === "string" && image.startsWith("ghcr.io/")
    ? image.slice("ghcr.io/".length)
    : undefined;
  const workflowRepository = workflowURL.match(
    /^https:\/\/[A-Za-z0-9.-]+\/([^/]+\/[^/]+)\/actions\/runs\/[1-9]\d*$/,
  )?.[1];
  if (!repository || workflowRepository !== repository) {
    throw publicationError(
      "invalid_workflow_url",
      "Stable publication requires a workflow URL for the requested repository.",
    );
  }
  if (
    typeof releaseURL !== "string" ||
    !SAFE_RELEASE_URL_PATTERN.test(releaseURL) ||
    (!releaseURL.endsWith(`/tag/${releaseTag}`) && !/\/releases\/[1-9]\d*$/.test(releaseURL))
  ) {
    throw publicationError(
      "invalid_release_url",
      "Stable publication requires a validated release URL for the release tag.",
    );
  }
  const releaseRepository = releaseURL.match(
    /^https:\/\/[A-Za-z0-9.-]+\/([^/]+\/[^/]+)\/releases\//,
  )?.[1];
  if (releaseRepository !== repository) {
    throw publicationError(
      "invalid_release_url",
      "Stable publication requires a release URL for the requested repository.",
    );
  }
}

function rememberKnownInspection(progress, inspection) {
  if (!inspection) return;
  progress.knownDigest = inspection.digest;
  progress.knownIndex = inspection.index;
  progress.knownPlatforms = inspection.platforms;
}

function safeReleaseTag(value) {
  return typeof value === "string" && /^v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/.test(value)
    ? value
    : undefined;
}

function safeVersionFileValue(root) {
  try {
    const contents = fs.readFileSync(path.join(root, "VERSION"), "utf8");
    if (!/^\S+\n?$/.test(contents)) return undefined;
    const value = contents.trim();
    return VERSION_PATTERN.test(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

async function safeCheckedOutRevision(root) {
  try {
    const value = commandOutput(await runCommand("git", ["rev-parse", "HEAD"], { cwd: root })).trim();
    return REVISION_PATTERN.test(value) ? value : undefined;
  } catch {
    return undefined;
  }
}

async function captureReleaseIdentity(root, releaseTag, expectedRevision) {
  const safeTag = safeReleaseTag(releaseTag);
  const checkedOutVersion = safeVersionFileValue(root);
  const identity = {
    ...(safeTag ? { releaseTag: safeTag, requestedVersion: safeTag.slice(1) } : {}),
    ...(checkedOutVersion ? { checkedOutVersion } : {}),
    ...(REVISION_PATTERN.test(String(expectedRevision ?? ""))
      ? { eventRevision: expectedRevision }
      : {}),
  };
  const checkedOutRevision = await safeCheckedOutRevision(root);
  if (checkedOutRevision) identity.checkedOutRevision = checkedOutRevision;
  return identity;
}

function appendGithubOutput(environment, evidence) {
  const outputPath = environment.GITHUB_OUTPUT;
  if (typeof outputPath !== "string" || !outputPath) return;
  const lines = [
    `publication_state=${evidence.state}`,
    `publication_digest=${evidence.digest}`,
    `publication_revision=${evidence.sourceRevision}`,
    `publication_platforms=${evidence.platforms.join(",")}`,
    `publication_workflow_url=${evidence.workflowURL ?? ""}`,
    `publication_evidence=${JSON.stringify(evidence)}`,
  ];
  fs.appendFileSync(outputPath, `${lines.join("\n")}\n`, { encoding: "utf8", mode: 0o600 });
}

function appendGithubSummary(environment, evidence) {
  const summaryPath = environment.GITHUB_STEP_SUMMARY;
  if (typeof summaryPath !== "string" || !summaryPath) return;
  const tagRows = evidence.actualTags
    .map((entry) => `| \`${entry.tag}\` | \`${entry.digest}\` | ${entry.platforms.map(({ name }) => name).join(", ")} |`)
    .join("\n");
  const summary = [
    "## Stable image publication",
    "",
    `- State: \`${evidence.state}\``,
    ...(evidence.version ? [`- Version: \`${evidence.version}\``] : []),
    ...(evidence.releaseTag ? [`- Release: \`${evidence.releaseTag}\``] : []),
    ...(evidence.sourceRevision ? [`- Source revision: \`${evidence.sourceRevision}\``] : []),
    ...(evidence.eventRevision ? [`- Event revision: \`${evidence.eventRevision}\``] : []),
    ...(evidence.checkedOutVersion ? [`- Checked-out version: \`${evidence.checkedOutVersion}\``] : []),
    ...(evidence.checkedOutRevision ? [`- Checked-out revision: \`${evidence.checkedOutRevision}\``] : []),
    ...(evidence.digest ? [`- Index digest: \`${evidence.digest}\``] : []),
    ...(Array.isArray(evidence.platforms)
      ? [`- Platforms: ${evidence.platforms.map((value) => `\`${value}\``).join(", ")}`]
      : []),
    ...(evidence.workflowURL ? [`- Workflow: ${evidence.workflowURL}`] : []),
    ...(evidence.releaseURL ? [`- Release: ${evidence.releaseURL}`] : []),
    ...(evidence.error ? [`- Error: \`${evidence.error}\``] : []),
    ...(evidence.nextAction ? [`- Next action: ${evidence.nextAction}`] : []),
    "",
    "| Tag | Digest | Runtime platforms |",
    "| --- | --- | --- |",
    tagRows,
    "",
  ].join("\n");
  fs.appendFileSync(summaryPath, summary, { encoding: "utf8", mode: 0o600 });
}

function writeEvidenceFile(environment, evidence) {
  const requested = environment.PUBLICATION_EVIDENCE_PATH;
  if (typeof requested !== "string" || !requested) return;
  if (path.isAbsolute(requested) || requested.split(/[\\/]/).some((part) => part === "..")) {
    throw publicationError("invalid_evidence_path", "Publication evidence path must remain inside the workspace.");
  }
  const root = environment.GITHUB_WORKSPACE ?? process.cwd();
  const destination = path.resolve(root, requested);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, `${JSON.stringify(evidence, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
}

function blockedPublicationEvidence(environment, error, context, image, identity = {}) {
  const publication = error instanceof ReleasePublicationError
    ? error.details?.publication
    : undefined;
  const releaseTag = publication?.releaseTag ?? context?.releaseTag ?? identity.releaseTag;
  const version = publication?.version ?? context?.version ?? identity.requestedVersion;
  const safeImage = typeof image === "string" && IMAGE_PATTERN.test(image) ? image : undefined;
  const safeReleaseTagValue = safeReleaseTag(releaseTag);
  const safeVersion = typeof version === "string" && VERSION_PATTERN.test(version) ? version : undefined;
  const safeRevision = typeof publication?.sourceRevision === "string" && REVISION_PATTERN.test(publication.sourceRevision)
    ? publication.sourceRevision
    : context?.revision;
  const safeDigest = validateDigest(publication?.digest) ? publication.digest : undefined;
  const safePlatforms = Array.isArray(publication?.platforms)
    ? publication.platforms.filter((platform) => REQUIRED_PLATFORM_NAMES.includes(platform?.name))
    : [];
  const safeActualTags = Array.isArray(publication?.actualTags) ? publication.actualTags : [];
  const safeWorkflow = safeWorkflowURL(environment);
  const safeRelease = safeReleaseTagValue ? safeReleaseURL(environment, safeReleaseTagValue) : undefined;
  const safeRecovery = publication?.recovery === "ambiguous" || publication?.recovery === "unverified"
    ? publication.recovery
    : undefined;
  const evidence = {
    schemaVersion: PUBLICATION_SCHEMA_VERSION,
    operation: "stable-image-publication",
    state: "blocked",
    ...(safeImage ? { image: safeImage } : {}),
    ...(safeVersion ? { version: safeVersion } : {}),
    ...(safeReleaseTagValue ? { releaseTag: safeReleaseTagValue } : {}),
    ...(safeRevision ? { sourceRevision: safeRevision } : {}),
    ...(identity.requestedVersion && VERSION_PATTERN.test(identity.requestedVersion)
      ? { requestedVersion: identity.requestedVersion }
      : {}),
    ...(identity.checkedOutVersion && VERSION_PATTERN.test(identity.checkedOutVersion)
      ? { checkedOutVersion: identity.checkedOutVersion }
      : {}),
    ...(identity.eventRevision && REVISION_PATTERN.test(identity.eventRevision)
      ? { eventRevision: identity.eventRevision }
      : {}),
    ...(identity.checkedOutRevision && REVISION_PATTERN.test(identity.checkedOutRevision)
      ? { checkedOutRevision: identity.checkedOutRevision }
      : {}),
    ...(safeDigest ? { digest: safeDigest } : {}),
    ...(publication?.immutableReference ? { immutableReference: publication.immutableReference } : {}),
    ...(publication?.index ? { index: publication.index } : {}),
    platforms: safePlatforms,
    actualTags: safeActualTags,
    ...(safeWorkflow ? { workflowURL: safeWorkflow } : {}),
    ...(safeRelease ? { releaseURL: safeRelease } : {}),
    ...(safeRecovery ? { recovery: safeRecovery } : {}),
    error: safeFailure(error),
    nextAction: safeRecovery === "ambiguous"
      ? "Reconcile the immutable image identity before retrying; do not rebuild an unverified tag."
      : "Review the recorded identity and rerun after the blocker is resolved.",
  };
  return evidence;
}

export async function runPublicationFromEnvironment(environment = process.env) {
  const releaseTag = environment.RELEASE_TAG;
  const root = environment.GITHUB_WORKSPACE ?? process.cwd();
  const repository = environment.GITHUB_REPOSITORY;
  const image = environment.IMAGE_NAME ?? `ghcr.io/${repository ?? ""}`;
  const identity = await captureReleaseIdentity(root, releaseTag, environment.GITHUB_SHA);
  let context;
  try {
    if (environment.RELEASE_PRERELEASE !== "false" || environment.RELEASE_DRAFT !== "false") {
      throw publicationError(
        "unstable_release",
        "Stable publication requires RELEASE_PRERELEASE=false and RELEASE_DRAFT=false.",
      );
    }
    const workflowURL = safeWorkflowURL(environment);
    if (!workflowURL) {
      throw publicationError("invalid_workflow_url", "Stable publication requires a validated workflow URL.");
    }
    const candidateReleaseTag = safeReleaseTag(releaseTag);
    const releaseURL = candidateReleaseTag ? safeReleaseURL(environment, candidateReleaseTag) : undefined;
    if (!releaseURL) {
      throw publicationError("invalid_release_url", "Stable publication requires a validated release URL.");
    }
    context = await readReleaseContext(root, releaseTag, environment.GITHUB_SHA);
    const registry = createDockerRegistryClient({ cwd: root });
    const evidence = await publishStableImage({
      image,
      releaseTag: context.releaseTag,
      version: context.version,
      revision: context.revision,
      registry,
      workflowURL,
      releaseURL,
      allowInitialImmutableAbsence: String(environment.GITHUB_RUN_ATTEMPT ?? "1") === "1",
    });
    writeEvidenceFile(environment, evidence);
    appendGithubOutput(environment, evidence);
    appendGithubSummary(environment, evidence);
    return evidence;
  } catch (error) {
    const failure = blockedPublicationEvidence(environment, error, context, image, identity);
    try {
      writeEvidenceFile(environment, failure);
    } catch {
      // Preserve the original typed failure if the requested evidence path is unusable.
    }
    try {
      appendGithubSummary(environment, failure);
    } catch {
      // Preserve the original typed failure if the summary path is unusable.
    }
    throw error;
  }
}

function safeFailure(error) {
  if (error instanceof ReleasePublicationError) {
    const diagnostic = error.details?.diagnostic;
    const suffix =
      typeof diagnostic === "string" && diagnostic !== "" ? ` (${diagnostic})` : "";
    return `${error.code}: ${error.message}${suffix}`;
  }
  return "publication_failed: stable image publication stopped unexpectedly.";
}

const isMain =
  process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));

if (isMain) {
  runPublicationFromEnvironment().catch((error) => {
    console.error(`Stable image publication blocked: ${safeFailure(error)}`);
    process.exitCode = 1;
  });
}
