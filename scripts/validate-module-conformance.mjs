import crypto from "node:crypto";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";
import { parse as parseToml } from "smol-toml";

const modulePackages = [
  ["metadata-manual", "media_finder_metadata_manual"],
  ["metadata-tmdb", "media_finder_metadata_tmdb"],
  ["release-prowlarr", "media_finder_release_prowlarr"],
  ["download-qbittorrent", "media_finder_download_qbittorrent"],
];
const redactionMarkers = ["artifact-body", "environment-values", "private-selection"];
const failureMatrix = {
  manual: [
    ["fetch-invalid-identity", "invalid-identity", "manual_import_invalid"],
    ["import-invalid-document", "invalid-identity", "manual_import_invalid"],
  ],
  tmdb: [
    ["fetch-invalid-identity", "invalid-identity", "metadata_identity_invalid"],
    ["search-unavailable", "unavailable", "metadata_provider_unavailable"],
  ],
  prowlarr: [
    ["resolve-invalid-selection", "invalid-request", "release_selection_invalid"],
    ["resolve-torrent-limit", "limit-exceeded", "release_torrent_too_large"],
    ["search-response-limit", "limit-exceeded", "release_response_too_large"],
    ["search-result-limit", "limit-exceeded", "release_result_limit_exceeded"],
  ],
  qbittorrent: [
    ["lookup-inconclusive", "inconclusive", "correlation_lookup_inconclusive"],
    ["submit-invalid-destination", "invalid-request", "download_destination_unavailable"],
    ["submit-timeout", "timeout", "submission_timeout"],
  ],
};
const credentialMarker = /(?:api[-_]?key|bearer|credential|passkey|password|secret|session|token)/i;
const credentialAssignment =
  /(?:api[-_]?key|bearer|credential|passkey|password|secret|session|token)\s*[:=]/i;
const publicPath = /^\/(?:[A-Za-z0-9._~-]+\/)*[A-Za-z0-9._~-]*$/;
const dnsLabel = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
const syntheticDocumentationSuffix = ".example.test";
const nonPublicDnsSuffixes = [
  "alt",
  "example",
  "home",
  "home.arpa",
  "internal",
  "invalid",
  "lan",
  "local",
  "localdomain",
  "localhost",
  "onion",
  "private",
  "test",
];
const nonPublicIpv4Cidrs = [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10],
  ["127.0.0.0", 8],
  ["169.254.0.0", 16],
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.0.2.0", 24],
  ["192.88.99.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["198.51.100.0", 24],
  ["203.0.113.0", 24],
  ["224.0.0.0", 3],
];
const publicIpv6Cidr = ["2000::", 3];
const nonPublicIpv6Cidrs = [
  ["2001::", 23],
  ["2001:db8::", 32],
  ["2002::", 16],
];
const forbiddenKeys = new Set([
  "artifact_body",
  "content",
  "environment_values",
  "magnet_uri",
  "payload",
  "private_selection",
  "torrent_bytes",
]);

function sortJson(value) {
  if (Array.isArray(value)) {
    return value.map(sortJson);
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, sortJson(item)]),
    );
  }
  return value;
}

function canonicalJson(value) {
  return `${JSON.stringify(sortJson(value), null, 2)}\n`;
}

function stableArray(values) {
  return [...values].sort((left, right) => left.localeCompare(right));
}

function asEnvironment(manifest) {
  return (manifest.environment ?? []).map((entry) => ({
    description_key: entry.description_key,
    name: entry.name,
    required: entry.required,
    secret: entry.secret,
  }));
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}

function stripUnsupportedDiscriminatorMappings(value) {
  if (Array.isArray(value)) {
    value.forEach(stripUnsupportedDiscriminatorMappings);
    return;
  }
  if (value === null || typeof value !== "object") {
    return;
  }
  if (value.discriminator?.propertyName === "applicable") {
    delete value.discriminator;
  } else if (value.discriminator) {
    delete value.discriminator.mapping;
  }
  Object.values(value).forEach(stripUnsupportedDiscriminatorMappings);
}

function scanForbiddenKeys(value, location, failures) {
  if (Array.isArray(value)) {
    value.forEach((item, index) => scanForbiddenKeys(item, `${location}[${index}]`, failures));
    return;
  }
  if (value === null || typeof value !== "object") {
    return;
  }
  for (const [key, item] of Object.entries(value)) {
    if (forbiddenKeys.has(key)) {
      failures.push(`${location}: private field ${key} must never be serialized`);
    }
    scanForbiddenKeys(item, `${location}.${key}`, failures);
  }
}

function scanSensitivePublicValues(value, location, failures) {
  if (Array.isArray(value)) {
    value.forEach((item, index) =>
      scanSensitivePublicValues(item, `${location}[${index}]`, failures),
    );
    return;
  }
  if (value === null || typeof value !== "object") {
    if (
      typeof value === "string" &&
      (credentialAssignment.test(value) ||
        (location.includes(".safe_details") && credentialMarker.test(value)) ||
        /https?:\/\/[^/\s]*@/i.test(value))
    ) {
      failures.push(`${location}: sensitive public value is forbidden`);
    }
    return;
  }
  for (const [key, item] of Object.entries(value)) {
    if (credentialMarker.test(key)) {
      failures.push(`${location}.${key}: sensitive public key is forbidden`);
    }
    scanSensitivePublicValues(item, `${location}.${key}`, failures);
  }
}

function validateRedactionProbes(fixture, label, failures) {
  const probes = Object.values(fixture.redaction_probes ?? {});
  if (probes.length !== 4 || new Set(probes).size !== 4) {
    failures.push(`${label}: redaction probes are missing or duplicated`);
    return;
  }
  const publicFixture = structuredClone(fixture);
  delete publicFixture.redaction_probes;
  const rendered = JSON.stringify(publicFixture);
  for (const probe of probes) {
    if (rendered.includes(probe)) {
      failures.push(`${label}: redaction probe leaked outside its declaration`);
    }
  }
}

function validateFailureMatrix(fixture, label, failures) {
  const expected = failureMatrix[fixture.module_id];
  const actual = fixture.stable_failures.map((failure) => [
    failure.operation,
    failure.error.category,
    failure.error.code,
  ]);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    failures.push(`${label}: stable failure matrix is incomplete or has drifted`);
  }
  for (const failure of fixture.stable_failures) {
    if (Object.keys(failure.error.safe_details).length !== 0) {
      failures.push(`${label}: stable failure safe_details must be empty and value-free`);
    }
  }
}

function isPublicHost(hostname) {
  const host = hostname.replace(/^\[|\]$/g, "").replace(/\.$/, "").toLowerCase();
  const family = net.isIP(host);
  if (family === 0) {
    const labels = host.split(".");
    if (
      host.length > 253 ||
      labels.length < 2 ||
      /^\d+$/.test(labels.at(-1)) ||
      !labels.every((label) => dnsLabel.test(label))
    ) {
      return false;
    }
    // Only repository fixtures may use this documented synthetic namespace.
    if (host.endsWith(syntheticDocumentationSuffix)) {
      return host !== syntheticDocumentationSuffix.slice(1);
    }
    return !nonPublicDnsSuffixes.some(
      (suffix) => host === suffix || host.endsWith(`.${suffix}`),
    );
  }
  if (family === 4) {
    const value = ipv4ToBigInt(host);
    return !nonPublicIpv4Cidrs.some(([network, prefix]) =>
      cidrContains(value, ipv4ToBigInt(network), prefix, 32),
    );
  }
  const value = ipv6ToBigInt(host);
  return (
    cidrContains(value, ipv6ToBigInt(publicIpv6Cidr[0]), publicIpv6Cidr[1], 128) &&
    !nonPublicIpv6Cidrs.some(([network, prefix]) =>
      cidrContains(value, ipv6ToBigInt(network), prefix, 128),
    )
  );
}

function ipv4ToBigInt(host) {
  return host
    .split(".")
    .map(Number)
    .reduce((value, octet) => (value << 8n) | BigInt(octet), 0n);
}

function ipv6ToBigInt(host) {
  let normalized = host;
  if (normalized.includes(".")) {
    const separator = normalized.lastIndexOf(":");
    const ipv4 = ipv4ToBigInt(normalized.slice(separator + 1));
    normalized = `${normalized.slice(0, separator)}:${(ipv4 >> 16n).toString(16)}:${(
      ipv4 & 0xffffn
    ).toString(16)}`;
  }
  const [leftText, rightText] = normalized.split("::");
  const left = leftText ? leftText.split(":") : [];
  const right = rightText ? rightText.split(":") : [];
  const groups = normalized.includes("::")
    ? [...left, ...Array(8 - left.length - right.length).fill("0"), ...right]
    : left;
  return groups.reduce((value, group) => (value << 16n) | BigInt(`0x${group || "0"}`), 0n);
}

function cidrContains(value, network, prefix, bits) {
  const shift = BigInt(bits - prefix);
  return value >> shift === network >> shift;
}

function isSafePublicSource(source) {
  if (source !== source.trim() || [...source].some((character) => character.codePointAt(0) < 32)) {
    return false;
  }
  if (
    source.includes("?") ||
    source.includes("#") ||
    /(?:^|\/)\.{1,2}(?:\/|$)/.test(source) ||
    /^https?:\/\/[^/]*@/i.test(source)
  ) {
    return false;
  }
  let url;
  try {
    url = new URL(source);
  } catch {
    return false;
  }
  const pathSegments = url.pathname.split("/").filter(Boolean);
  return (
    (url.protocol === "http:" || url.protocol === "https:") &&
    !url.username &&
    !url.password &&
    !url.search &&
    !url.hash &&
    !source.includes("%") &&
    !source.includes("\\") &&
    !source.includes(";") &&
    isPublicHost(url.hostname) &&
    publicPath.test(url.pathname) &&
    pathSegments.every(
      (segment) => segment !== "." && segment !== ".." && !credentialMarker.test(segment),
    )
  );
}

function compareManifest(fixture, manifest, manifestBytes, label, failures) {
  const comparisons = [
    ["module_id", manifest.module_id],
    ["module_kind", manifest.module_kind],
    ["module_version", manifest.module_version],
    ["sdk_compatibility", manifest.sdk_compatibility],
    ["contract_version", manifest.contract_version],
  ];
  for (const [key, expected] of comparisons) {
    if (fixture[key] !== expected) {
      failures.push(`${label}: ${key} does not match module.toml`);
    }
  }
  if (JSON.stringify(fixture.capabilities) !== JSON.stringify(stableArray(manifest.capabilities))) {
    failures.push(`${label}: capabilities do not match module.toml`);
  }
  if (JSON.stringify(fixture.environment) !== JSON.stringify(asEnvironment(manifest))) {
    failures.push(`${label}: environment declarations do not match module.toml`);
  }
  if (fixture.manifest_sha256 !== sha256(manifestBytes)) {
    failures.push(`${label}: manifest_sha256 does not match module.toml`);
  }

  const declaredRequired = asEnvironment(manifest)
    .filter((entry) => entry.required)
    .map((entry) => entry.name);
  const required = [...declaredRequired].sort();
  const missing = fixture.missing_configuration;
  if (required.length === 0) {
    if (missing.applicable !== false) {
      failures.push(`${label}: configuration-free module must mark missing configuration inapplicable`);
    }
  } else if (
    missing.applicable !== true ||
    JSON.stringify(missing.omitted) !== JSON.stringify(required) ||
    missing.error?.category !== "configuration" ||
    missing.error?.code !== "module_environment_missing" ||
    JSON.stringify(missing.error?.safe_details) !==
      JSON.stringify({ missing_names: declaredRequired })
  ) {
    failures.push(`${label}: missing-configuration case does not cover every required variable`);
  }
}

function validateMetadataSemantics(fixture, label, failures) {
  const { identity, normalized, query, results, retention } = fixture.success;
  if (results.length > query.limit) {
    failures.push(`${label}: metadata results exceed the declared query limit`);
  }
  if (
    !results.some(
      (result) =>
        result.provider_id === identity.provider_id &&
        result.external_id === identity.external_id &&
        result.media_kind === identity.media_kind &&
        result.locale === identity.locale,
    )
  ) {
    failures.push(`${label}: metadata success does not contain its declared identity`);
  }
  if (
    normalized.kind !== identity.media_kind ||
    normalized.provenance.provider_id !== identity.provider_id ||
    normalized.provenance.external_id !== identity.external_id ||
    normalized.provenance.locale !== identity.locale
  ) {
    failures.push(`${label}: normalized metadata identity or locale is inconsistent`);
  }
  if (Date.parse(retention.now) < Date.parse(retention.created_at)) {
    failures.push(`${label}: retention clock precedes metadata creation`);
  }
}

function validateArtifactDescriptor(descriptor, label, failures) {
  if (!Number.isInteger(descriptor.byte_length) || descriptor.byte_length < 1) {
    failures.push(`${label}: artifact descriptor has an invalid byte length`);
  }
  if (!/^[0-9a-f]{64}$/.test(descriptor.sha256)) {
    failures.push(`${label}: artifact descriptor has an invalid SHA-256 digest`);
  }
}

function validateReleaseSemantics(fixture, label, failures) {
  const { query, resolved_artifacts: artifacts, results } = fixture.success;
  if (results.length > query.limit) {
    failures.push(`${label}: release results exceed the declared query limit`);
  }
  const references = new Set(results.map((result) => result.selection_ref));
  if (references.size !== results.length) {
    failures.push(`${label}: release selection_ref values must be unique`);
  }
  for (const result of results) {
    const guid = result.snapshot.guid;
    if (
      guid &&
      (!/^[A-Za-z0-9._:-]{1,255}$/.test(guid) || credentialMarker.test(guid))
    ) {
      failures.push(`${label}: safe release snapshot GUID is invalid or credential-like`);
    }
    const source = result.snapshot.source_page_url;
    if (source && !isSafePublicSource(source)) {
      failures.push(`${label}: safe release snapshot contains a sensitive URL component`);
    }
  }
  for (const resolved of artifacts) {
    if (!references.has(resolved.selection_ref)) {
      failures.push(`${label}: resolved artifact uses an unknown selection_ref`);
    }
    validateArtifactDescriptor(resolved.artifact, label, failures);
  }
  const declaredKinds = stableArray(
    fixture.capabilities.filter((capability) => capability === "magnet" || capability === "torrent"),
  );
  const fixtureKinds = stableArray(new Set(artifacts.map((resolved) => resolved.artifact.kind)));
  if (JSON.stringify(declaredKinds) !== JSON.stringify(fixtureKinds)) {
    failures.push(`${label}: release artifact descriptors do not cover declared capabilities`);
  }
}

function validateDownloadSemantics(fixture, label, failures) {
  const success = fixture.success;
  const destinationKeys = new Set(success.destinations.map((destination) => destination.key));
  if (!destinationKeys.has(success.destination)) {
    failures.push(`${label}: selected destination is absent from live destinations`);
  }
  if (
    success.submission.correlation !== success.correlation ||
    success.lookup.correlation !== success.correlation
  ) {
    failures.push(`${label}: submission and lookup do not preserve exact correlation`);
  }
  success.artifacts.forEach((artifact) => validateArtifactDescriptor(artifact, label, failures));
  const declaredKinds = stableArray(
    fixture.capabilities.filter((capability) => capability === "magnet" || capability === "torrent"),
  );
  const fixtureKinds = stableArray(new Set(success.artifacts.map((artifact) => artifact.kind)));
  if (JSON.stringify(declaredKinds) !== JSON.stringify(fixtureKinds)) {
    failures.push(`${label}: download artifact descriptors do not cover declared capabilities`);
  }
}

function validateSemanticFixture(fixture, manifest, manifestBytes, label, failures) {
  compareManifest(fixture, manifest, manifestBytes, label, failures);
  if (JSON.stringify(fixture.redaction_markers) !== JSON.stringify(redactionMarkers)) {
    failures.push(`${label}: required redaction markers are incomplete or non-canonical`);
  }
  const fixtureWithoutProbeDeclarations = structuredClone(fixture);
  delete fixtureWithoutProbeDeclarations.redaction_probes;
  scanForbiddenKeys(fixtureWithoutProbeDeclarations, label, failures);
  validateRedactionProbes(fixture, label, failures);
  validateFailureMatrix(fixture, label, failures);
  const publicFixture = structuredClone(fixture);
  delete publicFixture.environment;
  delete publicFixture.redaction_probes;
  if (publicFixture.missing_configuration?.applicable === true) {
    // missing_names is already checked exactly against value-free manifest
    // declarations by compareManifest; it is not credential material.
    publicFixture.missing_configuration.error.safe_details = {};
  }
  // Exact environment variable names and probe values are declarations, not
  // public outputs. Everything else must remain free of credential material.
  scanSensitivePublicValues(publicFixture, label, failures);
  if (fixture.module_kind === "metadata-provider") {
    validateMetadataSemantics(fixture, label, failures);
  } else if (fixture.module_kind === "release-provider") {
    validateReleaseSemantics(fixture, label, failures);
  } else if (fixture.module_kind === "download-client") {
    validateDownloadSemantics(fixture, label, failures);
  }
}

export function validateModuleConformance(root = process.cwd()) {
  const failures = [];
  const schemaPath = path.join(root, "schemas", "module-sdk", "v1", "conformance.schema.json");
  let validate;
  try {
    const schema = JSON.parse(fs.readFileSync(schemaPath, "utf8"));
    // Ajv implements the draft discriminator keyword but intentionally omits
    // OpenAPI's explicit mapping extension. The generated oneOf constants are
    // the source of truth, so the mapping is used by other consumers and can
    // be removed from Ajv's in-memory copy without weakening validation.
    stripUnsupportedDiscriminatorMappings(schema);
    const ajv = new Ajv2020({
      allErrors: true,
      discriminator: true,
      strict: true,
      strictTypes: false,
    });
    addFormats(ajv);
    validate = ajv.compile(schema);
  } catch (error) {
    return [`${schemaPath}: unable to load conformance schema: ${error.message}`];
  }

  for (const [workspaceName, importName] of modulePackages) {
    const packageRoot = path.join(root, "packages", "modules", workspaceName, "src", importName);
    const manifestPath = path.join(packageRoot, "module.toml");
    const fixturePath = path.join(packageRoot, "fixtures", "conformance.json");
    const label = path.relative(root, fixturePath).replaceAll("\\", "/");
    try {
      const manifestBytes = fs.readFileSync(manifestPath);
      const manifest = parseToml(manifestBytes.toString("utf8"));
      const fixtureBytes = fs.readFileSync(fixturePath, "utf8");
      const fixture = JSON.parse(fixtureBytes);
      if (fixtureBytes !== canonicalJson(fixture)) {
        failures.push(`${label}: fixture is not canonical JSON`);
      }
      if (!validate(fixture)) {
        failures.push(
          `${label}: schema validation failed: ${validate.errors
            .map((error) => `${error.instancePath || "/"} ${error.message}`)
            .join("; ")}`,
        );
        continue;
      }
      validateSemanticFixture(fixture, manifest, manifestBytes, label, failures);
    } catch (error) {
      failures.push(`${label}: unable to validate fixture: ${error.message}`);
    }
  }
  return failures;
}

const isMain =
  process.argv[1] !== undefined &&
  path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (isMain) {
  const failures = validateModuleConformance();
  if (failures.length) {
    console.error(failures.join("\n"));
    process.exit(1);
  }
  console.log("Serialized module conformance fixtures are valid and canonical.");
}
