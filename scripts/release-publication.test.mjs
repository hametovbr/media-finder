import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  createDockerRegistryClient,
  expectedImageTags,
  parseRegistryInspection,
  publishStableImage,
  readReleaseContext,
  runPublicationFromEnvironment,
} from "./release-publication.mjs";
import { validatePublicationEvidence } from "./release-automation.mjs";

const IMAGE = "ghcr.io/acme/media-finder";
const VERSION = "1.2.3";
const REVISION = "a".repeat(40);
const OTHER_REVISION = "b".repeat(40);
const PLATFORM_DIGESTS = {
  "linux/amd64": `sha256:${"4".repeat(64)}`,
  "linux/arm64": `sha256:${"5".repeat(64)}`,
};

function descriptor(platform, digest, annotations) {
  const [os, architecture] = platform.split("/");
  return {
    mediaType: "application/vnd.oci.image.manifest.v1+json",
    digest,
    size: 123,
    ...(annotations ? { annotations } : {}),
    platform: { os, architecture },
  };
}

function imageDetails(version, revision, platforms = ["linux/amd64", "linux/arm64"]) {
  return Object.fromEntries(
    platforms.map((platform) => [
      platform,
      {
        config: {
          Labels: {
            "org.opencontainers.image.version": version,
            "org.opencontainers.image.revision": revision,
          },
        },
      },
    ]),
  );
}

function registryInspection({
  version = VERSION,
  revision = REVISION,
  platforms = ["linux/amd64", "linux/arm64"],
  includeAttestation = true,
  platformDetails = platforms,
  variant,
  formattedDigest,
} = {}) {
  const manifests = platforms.map((platform) =>
    descriptor(platform, PLATFORM_DIGESTS[platform] ?? `sha256:${"6".repeat(64)}`),
  );
  if (includeAttestation) {
    manifests.push(
      descriptor("linux/unknown", `sha256:${"7".repeat(64)}`, {
        "vnd.docker.reference.type": "attestation-manifest",
      }),
    );
  }
  const rawManifest = {
      schemaVersion: 2,
      mediaType: "application/vnd.oci.image.index.v1+json",
      ...(variant ? { annotations: { "org.example.fixture.variant": variant } } : {}),
      manifests,
  };
  const raw = JSON.stringify(rawManifest);
  const digest = `sha256:${createHash("sha256").update(raw).digest("hex")}`;
  return {
    raw,
    formatted: {
      name: `${IMAGE}:fixture`,
      manifest: {
        schemaVersion: 2,
        mediaType: "application/vnd.oci.image.index.v1+json",
        ...(formattedDigest ? { digest: formattedDigest } : { digest }),
        ...(variant ? { annotations: { "org.example.fixture.variant": variant } } : {}),
        manifests,
      },
      image: imageDetails(version, revision, platformDetails),
    },
  };
}

const IMMUTABLE_DIGEST = registryInspection().formatted.manifest.digest;
const OTHER_DIGEST = registryInspection({ variant: "other" }).formatted.manifest.digest;
const LATER_DIGEST = registryInspection({ version: "1.2.4", revision: OTHER_REVISION }).formatted.manifest.digest;

function expectedRefs(version = VERSION) {
  return expectedImageTags(IMAGE, version);
}

class FixtureRegistry {
  constructor(refs = {}, { buildVersion = VERSION, buildRevision = REVISION } = {}) {
    this.refs = new Map(Object.entries(refs));
    this.buildVersion = buildVersion;
    this.buildRevision = buildRevision;
    this.events = [];
    this.buildCount = 0;
    this.retagCount = 0;
  }

  async inspect(ref) {
    this.events.push(["inspect", ref]);
    const value = this.refs.get(ref);
    return value === undefined ? undefined : structuredClone(value);
  }

  async build({ ref }) {
    this.events.push(["build", ref]);
    this.buildCount += 1;
    this.refs.set(
      ref,
      registryInspection({ version: this.buildVersion, revision: this.buildRevision }),
    );
  }

  async retag({ source, destination }) {
    this.events.push(["retag", source, destination]);
    this.retagCount += 1;
    const sourceRef = source.split("@")[0];
    const sourceInspection = this.refs.get(sourceRef);
    assert.ok(sourceInspection, `fixture source ${sourceRef} must exist`);
    this.refs.set(destination, structuredClone(sourceInspection));
  }
}

function publish(registry, overrides = {}) {
  return publishStableImage({
    image: IMAGE,
    releaseTag: `v${VERSION}`,
    version: VERSION,
    revision: REVISION,
    workflowURL: "https://github.com/acme/media-finder/actions/runs/42",
    releaseURL: "https://github.com/acme/media-finder/releases/tag/v1.2.3",
    registry,
    ...overrides,
  });
}

function createGitFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "release-publication-"));
  const git = (args) => execFileSync("git", args, {
    cwd: root,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
  git(["init", "--quiet"]);
  git(["config", "user.email", "release-fixture@example.invalid"]);
  git(["config", "user.name", "Release Fixture"]);
  fs.writeFileSync(path.join(root, "VERSION"), `${VERSION}\n`);
  git(["add", "VERSION"]);
  git(["commit", "--quiet", "-m", "initial"]);
  const revision = git(["rev-parse", "HEAD"]);
  git(["tag", `v${VERSION}`]);
  return { root, revision };
}

test("registry parsing ignores attestation descriptors and retains both runtime platforms", () => {
  const parsed = parseRegistryInspection(registryInspection());

  assert.equal(parsed.digest, IMMUTABLE_DIGEST);
  assert.deepEqual(parsed.platforms.map(({ name }) => name), ["linux/amd64", "linux/arm64"]);
  assert.deepEqual(
    parsed.platforms.map(({ sourceRevision }) => sourceRevision),
    [REVISION, REVISION],
  );
});

test("the Docker adapter hashes raw bytes and inspects labels at the derived digest", async () => {
  const tags = expectedRefs();
  const calls = [];
  const client = createDockerRegistryClient({
    command: async (program, args) => {
      calls.push([program, args]);
      if (args.includes("--raw")) {
        return registryInspection().raw;
      }
      assert.equal(args.at(-1), `${tags.immutable}@${IMMUTABLE_DIGEST}`);
      return JSON.stringify(registryInspection().formatted);
    },
  });

  const inspection = parseRegistryInspection(await client.inspect(tags.immutable));

  assert.equal(inspection.digest, IMMUTABLE_DIGEST);
  assert.deepEqual(calls.map(([program]) => program), ["docker", "docker"]);
  assert.deepEqual(calls[0][1].slice(0, 4), ["buildx", "imagetools", "inspect", "--raw"]);
  assert.deepEqual(calls[1][1].slice(0, 4), ["buildx", "imagetools", "inspect", "--format"]);
});

test("only authoritative manifest absence is treated as an absent registry tag", async () => {
  const tags = expectedRefs();
  // Observed output of `docker buildx imagetools inspect` for a tag that does not
  // exist yet; this is what a first stable publication actually receives.
  const absence = Object.assign(new Error("command failed"), {
    status: 1,
    stderr: Buffer.from(`ERROR: ${tags.immutable}: not found\n`),
  });
  const client = createDockerRegistryClient({
    command: async () => {
      throw absence;
    },
  });

  assert.equal(await client.inspect(tags.immutable), undefined);
});

test("an inspection failure records the command diagnostic that identifies its cause", async () => {
  const tags = expectedRefs();
  const failure = Object.assign(new Error("command failed"), {
    status: 1,
    stderr: Buffer.from("denied: requested access to the resource is denied\n"),
  });
  const client = createDockerRegistryClient({
    command: async () => {
      throw failure;
    },
  });

  await assert.rejects(client.inspect(tags.immutable), (error) => {
    assert.equal(error.code, "registry_inspection_failed");
    assert.match(String(error.details?.diagnostic ?? ""), /denied: requested access/);
    return true;
  });
});

test("a pre-signed URL in the diagnostic never reaches the failure record", async () => {
  const tags = expectedRefs();
  const failure = Object.assign(new Error("command failed"), {
    status: 1,
    stderr: Buffer.from(
      "failed to fetch https://blob.example.test/x?sv=1&sig=aB9cSecretValue: context deadline\n",
    ),
  });
  const client = createDockerRegistryClient({
    command: async () => {
      throw failure;
    },
  });

  await assert.rejects(client.inspect(tags.immutable), (error) => {
    const diagnostic = String(error.details?.diagnostic ?? "");
    assert.match(diagnostic, /blob\.example\.test/);
    assert.equal(diagnostic.includes("sig="), false);
    assert.equal(diagnostic.includes("aB9cSecretValue"), false);
    return true;
  });
});

test("a command that failed without captured output still records its cause", async () => {
  const tags = expectedRefs();
  const failure = Object.assign(new Error("command timeout"), { code: "ETIMEDOUT" });
  const client = createDockerRegistryClient({
    command: async () => {
      throw failure;
    },
  });

  await assert.rejects(client.inspect(tags.immutable), (error) => {
    assert.equal(error.code, "registry_inspection_failed");
    assert.match(String(error.details?.diagnostic ?? ""), /ETIMEDOUT/);
    return true;
  });
});

test("generic 404, not-found, auth, and transport errors fail closed", async () => {
  const errors = [
    Object.assign(new Error("command failed"), {
      status: 1,
      stderr: Buffer.from("Error response from daemon: HTTP 404 not found\n"),
    }),
    Object.assign(new Error("HTTP 404"), { status: 404 }),
    Object.assign(new Error("not found"), { status: 404 }),
    Object.assign(new Error("unauthorized: authentication required"), { status: 404 }),
    Object.assign(new Error("network not found"), { code: "ENOTFOUND" }),
  ];

  for (const failure of errors) {
    const client = createDockerRegistryClient({
      command: async () => {
        throw failure;
      },
    });
    await assert.rejects(
      client.inspect(expectedRefs().immutable),
      (error) => error.code === "registry_inspection_failed",
    );
  }
});

test("a signal-terminated inspection never treats manifest text as authoritative absence", async () => {
  const failure = Object.assign(new Error("command failed"), {
    status: null,
    signal: "SIGTERM",
    stderr: Buffer.from("Error response from daemon: manifest unknown: manifest unknown\n"),
  });
  const client = createDockerRegistryClient({
    command: async () => {
      throw failure;
    },
  });

  await assert.rejects(
    client.inspect(expectedRefs().immutable),
    (error) => error.code === "registry_inspection_failed",
  );
});

test("disagreeing raw and formatted digests fail closed", async () => {
  const tags = expectedRefs();
  const client = createDockerRegistryClient({
    command: async (_program, args) =>
      args.includes("--raw")
        ? registryInspection().raw
        : JSON.stringify(registryInspection({ formattedDigest: OTHER_DIGEST }).formatted),
  });

  await assert.rejects(
    client.inspect(tags.immutable),
    (error) => error.code === "digest_mismatch",
  );
});

test("the Docker adapter builds one immutable tag and retags by digest", async () => {
  const tags = expectedRefs();
  const calls = [];
  const client = createDockerRegistryClient({
    command: async (program, args) => {
      calls.push([program, args]);
      return {};
    },
  });

  await client.build({ ref: tags.immutable, version: VERSION, revision: REVISION });
  await client.retag({
    source: `${tags.immutable}@${IMMUTABLE_DIGEST}`,
    destination: tags.latest,
  });

  assert.deepEqual(calls[0][1], [
    "buildx",
    "build",
    "--platform",
    "linux/amd64,linux/arm64",
    "--tag",
    tags.immutable,
    "--label",
    "org.opencontainers.image.version=1.2.3",
    "--label",
    `org.opencontainers.image.revision=${REVISION}`,
    "--provenance=mode=max",
    "--cache-from",
    "type=gha",
    "--cache-to",
    "type=gha,mode=max",
    "--push",
    ".",
  ]);
  assert.deepEqual(calls[1][1], [
    "buildx",
    "imagetools",
    "create",
    "--tag",
    tags.latest,
    `${tags.immutable}@${IMMUTABLE_DIGEST}`,
  ]);
});

test("malformed registry JSON is rejected without exposing the response", async () => {
  const client = createDockerRegistryClient({
    command: async (_program, args) =>
      args.includes("--raw") ? "{malformed" : JSON.stringify({}),
  });

  await assert.rejects(
    client.inspect(expectedRefs().immutable),
    (error) => error.code === "invalid_manifest",
  );
});

test("an incomplete but parseable registry response is rejected before publication", async () => {
  const client = createDockerRegistryClient({
    command: async (_program, args) =>
      args.includes("--raw") ? JSON.stringify({ schemaVersion: 2 }) : JSON.stringify({}),
  });

  await assert.rejects(
    client.inspect(expectedRefs().immutable),
    (error) => error.code === "invalid_manifest",
  );
});

test("a malformed existing immutable tag is never treated as absent", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry({
    [tags.immutable]: { raw: "{}", formatted: {} },
  });

  await assert.rejects(
    publish(registry),
    (error) => error.code === "invalid_manifest",
  );
  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 0);
});

test("tag/version mismatch blocks publication before any registry mutation", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry({
    [tags.immutable]: registryInspection({ version: "1.2.4" }),
  });

  await assert.rejects(
    publish(registry),
    (error) => error.code === "tag_version_mismatch",
  );
  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 0);
});

test("immutable source revision mismatch is rejected without reusing the tag", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry({
    [tags.immutable]: registryInspection({ revision: OTHER_REVISION }),
  });

  await assert.rejects(
    publish(registry),
    (error) => error.code === "digest_revision_mismatch",
  );
  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 0);
});

test("missing architecture fails closed even when an attestation descriptor exists", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry({
    [tags.immutable]: registryInspection({ platforms: ["linux/amd64"] }),
  });

  await assert.rejects(
    publish(registry),
    (error) => error.code === "missing_architecture",
  );
  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 0);
});

test("a partial publication reuses the immutable digest and repairs only missing moving tags", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry({
    [tags.immutable]: registryInspection(),
    [tags.minor]: registryInspection(),
  });

  const result = await publish(registry);

  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 1);
  assert.equal(result.state, "repaired");
  assert.deepEqual(result.actualTags.map(({ tag }) => tag), ["v1.2.3", "1.2", "latest"]);
  assert.equal(result.digest, IMMUTABLE_DIGEST);
  assert.deepEqual(result.platforms, ["linux/amd64", "linux/arm64"]);
  assert.deepEqual(result.actualTags.map(({ name }) => name), ["v1.2.3", "1.2", "latest"]);
  assert.equal("tags" in result, false);
  assert.equal("revision" in result, false);
  assert.equal(result.sourceRevision, REVISION);
  assert.equal(result.workflowURL, "https://github.com/acme/media-finder/actions/runs/42");
});

test("a missing immutable tag can be restored from a verified same-version moving tag", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry({
    [tags.minor]: registryInspection(),
  });

  const result = await publish(registry);

  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 2);
  assert.equal(result.state, "repaired");
  assert.equal(result.digest, IMMUTABLE_DIGEST);
  assert.ok(registry.refs.has(tags.immutable));
  assert.ok(registry.refs.has(tags.latest));
});

test("a rerun can repair an absent immutable tag from a verified moving pointer", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry({
    [tags.minor]: registryInspection(),
  });

  const result = await publish(registry, { allowInitialImmutableAbsence: false });

  assert.equal(registry.buildCount, 0);
  assert.equal(result.state, "repaired");
  assert.equal(result.digest, IMMUTABLE_DIGEST);
  assert.ok(registry.refs.has(tags.immutable));
});

test("a retry after failure following the immutable push reconciles before repair", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry();
  let failAfterBuild = true;
  const originalBuild = registry.build.bind(registry);
  registry.build = async (input) => {
    await originalBuild(input);
    if (failAfterBuild) {
      failAfterBuild = false;
      throw new Error("simulated post-push timeout");
    }
  };

  await assert.rejects(publish(registry), (error) => {
    assert.equal(error.code, "build_failed");
    assert.equal(error.details.publication.digest, IMMUTABLE_DIGEST);
    assert.equal(error.details.publication.actualTags.length, 0);
    return true;
  });
  const result = await publish(registry);

  assert.equal(registry.buildCount, 1);
  assert.equal(result.state, "repaired");
  assert.equal(registry.retagCount, 2);
  assert.ok(registry.refs.has(tags.minor));
  assert.ok(registry.refs.has(tags.latest));
});

test("an uncertain post-build absence never triggers a second build", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry();
  const originalBuild = registry.build.bind(registry);
  registry.build = async (input) => {
    await originalBuild(input);
    throw new Error("simulated post-push timeout");
  };
  const originalInspect = registry.inspect.bind(registry);
  registry.inspect = async (ref) => {
    if (ref === tags.immutable && registry.buildCount > 0) {
      registry.events.push(["inspect", ref]);
      return undefined;
    }
    return originalInspect(ref);
  };

  await assert.rejects(
    publish(registry),
    (error) => error.code === "build_failed" && error.details.publication.recovery === "ambiguous",
  );
  assert.equal(registry.buildCount, 1);
  assert.equal(registry.retagCount, 0);
});

test("a successful build with an ambiguous verification read remains blocked", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry();
  const originalInspect = registry.inspect.bind(registry);
  registry.inspect = async (ref) => {
    if (ref === tags.immutable && registry.buildCount > 0) {
      registry.events.push(["inspect", ref]);
      return undefined;
    }
    return originalInspect(ref);
  };

  await assert.rejects(
    publish(registry),
    (error) => error.code === "registry_inspection_ambiguous" && error.details.publication.recovery === "ambiguous",
  );
  assert.equal(registry.buildCount, 1);
  assert.equal(registry.retagCount, 0);
});

test("a rerun with no verified immutable identity blocks instead of rebuilding", async () => {
  const registry = new FixtureRegistry();

  await assert.rejects(
    publish(registry, { allowInitialImmutableAbsence: false }),
    (error) => error.code === "registry_inspection_ambiguous",
  );
  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 0);
});

test("an already complete immutable publication is reused without a rebuild", async () => {
  const tags = expectedRefs();
  const complete = registryInspection();
  const registry = new FixtureRegistry({
    [tags.immutable]: complete,
    [tags.minor]: complete,
    [tags.latest]: complete,
  });

  const result = await publish(registry);

  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 0);
  assert.equal(result.state, "reused");
  assert.equal(result.index.digest, IMMUTABLE_DIGEST);
  assert.equal(result.actualTags[2].digest, IMMUTABLE_DIGEST);
});

test("an older rerun cannot downgrade either moving tag", async () => {
  const oldVersion = "1.2.2";
  const oldTags = expectedRefs(oldVersion);
  const newer = registryInspection({
    version: "1.2.4",
    revision: OTHER_REVISION,
    digest: LATER_DIGEST,
  });
  const registry = new FixtureRegistry({
    [oldTags.immutable]: registryInspection({ version: oldVersion }),
    [oldTags.minor]: newer,
    [oldTags.latest]: newer,
  });

  await assert.rejects(
    publish(registry, {
      releaseTag: `v${oldVersion}`,
      version: oldVersion,
      releaseURL: `https://github.com/acme/media-finder/releases/tag/v${oldVersion}`,
    }),
    (error) => error.code === "moving_tag_regression",
  );
  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 0);
  assert.equal(registry.refs.get(oldTags.minor).formatted.manifest.digest, LATER_DIGEST);
  assert.equal(registry.refs.get(oldTags.latest).formatted.manifest.digest, LATER_DIGEST);
});

test("same-version moving tag with a different digest is an immutable conflict", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry({
    [tags.immutable]: registryInspection(),
    [tags.minor]: registryInspection({ variant: "other" }),
  });

  await assert.rejects(
    publish(registry),
    (error) => error.code === "moving_tag_conflict",
  );
  assert.equal(registry.retagCount, 0);
});

test("source revision provenance is required independently for both architectures", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry({
    [tags.immutable]: registryInspection({
      platformDetails: ["linux/amd64"],
    }),
  });

  await assert.rejects(
    publish(registry),
    (error) => error.code === "digest_revision_mismatch",
  );
  assert.equal(registry.retagCount, 0);
});

test("concurrent calls for one image are serialized and do not build twice", async () => {
  const tags = expectedRefs();
  const registry = new FixtureRegistry();
  const originalBuild = registry.build.bind(registry);
  registry.build = async (input) => {
    await new Promise((resolve) => setTimeout(resolve, 10));
    return originalBuild(input);
  };

  const [first, second] = await Promise.all([publish(registry), publish(registry)]);

  assert.equal(registry.buildCount, 1);
  assert.equal(first.digest, second.digest);
  assert.ok(registry.refs.has(tags.latest));
});

test("release tag must equal the requested version before registry access", async () => {
  const registry = new FixtureRegistry();

  await assert.rejects(
    publish(registry, { releaseTag: "v1.2.4" }),
    (error) => error.code === "tag_version_mismatch",
  );
  assert.equal(registry.events.length, 0);
});

test("required publication URLs are validated before registry access", async () => {
  const registry = new FixtureRegistry();

  await assert.rejects(
    publish(registry, { workflowURL: undefined }),
    (error) => error.code === "invalid_workflow_url",
  );
  assert.equal(registry.events.length, 0);

  await assert.rejects(
    publish(registry, { releaseURL: undefined }),
    (error) => error.code === "invalid_release_url",
  );
  assert.equal(registry.events.length, 0);

  await assert.rejects(
    publish(registry, {
      workflowURL: "https://github.com/acme/other-repository/actions/runs/42",
    }),
    (error) => error.code === "invalid_workflow_url",
  );
  assert.equal(registry.events.length, 0);

  await assert.rejects(
    publish(registry, {
      releaseURL: "https://github.com/acme/other-repository/releases/tag/v1.2.3",
    }),
    (error) => error.code === "invalid_release_url",
  );
  assert.equal(registry.events.length, 0);
});

test("stable environment requires exact false release flags before checkout", async () => {
  await assert.rejects(
    runPublicationFromEnvironment({
      RELEASE_TAG: `v${VERSION}`,
      RELEASE_PRERELEASE: "false",
      RELEASE_DRAFT: "",
      GITHUB_WORKSPACE: path.join(os.tmpdir(), "missing-release-workspace"),
    }),
    (error) => error.code === "unstable_release",
  );
});

test("pre-context failures preserve event and checkout identity in evidence and summary", async () => {
  const { root, revision } = createGitFixture();
  const evidencePath = path.join(root, "evidence.json");
  const summaryPath = path.join(root, "summary.md");
  try {
    await assert.rejects(
      runPublicationFromEnvironment({
        RELEASE_TAG: `v${VERSION}`,
        RELEASE_PRERELEASE: "false",
        RELEASE_DRAFT: "false",
        GITHUB_SHA: OTHER_REVISION,
        GITHUB_WORKSPACE: root,
        GITHUB_SERVER_URL: "https://github.com",
        GITHUB_REPOSITORY: "acme/media-finder",
        GITHUB_RUN_ID: "42",
        RELEASE_URL: `https://github.com/acme/media-finder/releases/tag/v${VERSION}`,
        PUBLICATION_EVIDENCE_PATH: "evidence.json",
        GITHUB_STEP_SUMMARY: summaryPath,
      }),
      (error) => error.code === "checkout_revision_mismatch",
    );

    const evidence = JSON.parse(fs.readFileSync(evidencePath, "utf8"));
    const summary = fs.readFileSync(summaryPath, "utf8");
    assert.equal(evidence.releaseTag, `v${VERSION}`);
    assert.equal(evidence.version, VERSION);
    assert.equal(evidence.eventRevision, OTHER_REVISION);
    assert.equal(evidence.checkedOutVersion, VERSION);
    assert.equal(evidence.checkedOutRevision, revision);
    assert.match(evidence.error, /^checkout_revision_mismatch:/);
    assert.match(summary, /checkout_revision_mismatch/);
    assert.match(summary, new RegExp(revision));
    assert.match(summary, new RegExp(OTHER_REVISION));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("a tag moved after the release event is rejected against the captured SHA", async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "release-publication-"));
  const git = (args) => execFileSync("git", args, {
    cwd: root,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  }).trim();
  try {
    git(["init", "--quiet"]);
    git(["config", "user.email", "release-fixture@example.invalid"]);
    git(["config", "user.name", "Release Fixture"]);
    fs.writeFileSync(path.join(root, "VERSION"), `${VERSION}\n`);
    git(["add", "VERSION"]);
    git(["commit", "--quiet", "-m", "initial"]);
    const eventRevision = git(["rev-parse", "HEAD"]);
    git(["tag", `v${VERSION}`]);
    fs.writeFileSync(path.join(root, "marker"), "second\n");
    git(["add", "marker"]);
    git(["commit", "--quiet", "-m", "second"]);
    const movedTagRevision = git(["rev-parse", "HEAD"]);
    git(["checkout", "--quiet", "--detach", eventRevision]);
    git(["tag", "--force", `v${VERSION}`, movedTagRevision]);

    await assert.rejects(
      readReleaseContext(root, `v${VERSION}`, eventRevision),
      (error) => error.code === "checkout_revision_mismatch",
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("manually published stable Releases emit evidence the release controller validates", async () => {
  const refs = expectedRefs();
  const registry = new FixtureRegistry({});
  const published = await publish(registry, { allowInitialImmutableAbsence: true });
  assert.equal(published.state, "published");
  const checked = validatePublicationEvidence(published, {
    repository: "acme/media-finder",
    version: VERSION,
    mergedSha: REVISION,
    runId: 42,
    releaseURL: "https://github.com/acme/media-finder/releases/tag/v1.2.3",
  });
  assert.deepEqual(checked.actualTags.map(({ name }) => name), ["v1.2.3", "1.2", "latest"]);
  assert.deepEqual(checked.platforms, ["linux/amd64", "linux/arm64"]);
  assert.equal(checked.sourceRevision, REVISION);

  // A manually published Release whose pointer set is incomplete is repaired
  // through the same guarded path and still emits controller-valid evidence.
  const partial = new FixtureRegistry({ [refs.immutable]: registryInspection() });
  const repaired = await publish(partial, { allowInitialImmutableAbsence: false });
  assert.equal(repaired.state, "repaired");
  assert.equal(partial.buildCount, 0);
  const checkedRepair = validatePublicationEvidence(repaired, {
    repository: "acme/media-finder",
    version: VERSION,
    mergedSha: REVISION,
    runId: 42,
    releaseURL: "https://github.com/acme/media-finder/releases/tag/v1.2.3",
  });
  assert.equal(checkedRepair.digest, repaired.digest);

  // An already complete immutable publication is reused, never rebuilt, and the
  // reused evidence is validated by the same controller contract.
  const complete = new FixtureRegistry({
    [refs.immutable]: registryInspection(),
    [refs.minor]: registryInspection(),
    [refs.latest]: registryInspection(),
  });
  const reused = await publish(complete, { allowInitialImmutableAbsence: false });
  assert.equal(reused.state, "reused");
  assert.equal(complete.buildCount, 0);
  assert.equal(complete.retagCount, 0);
  assert.equal(validatePublicationEvidence(reused, {
    repository: "acme/media-finder",
    version: VERSION,
    mergedSha: REVISION,
    runId: 42,
    releaseURL: "https://github.com/acme/media-finder/releases/tag/v1.2.3",
  }).state, "reused");
});

test("a rerun of a manually published Release never rebuilds an absent immutable tag", async () => {
  const registry = new FixtureRegistry({});
  await assert.rejects(
    () => publish(registry, { allowInitialImmutableAbsence: false }),
    (error) => error.code === "registry_inspection_ambiguous",
  );
  assert.equal(registry.buildCount, 0);
  assert.equal(registry.retagCount, 0);
});
