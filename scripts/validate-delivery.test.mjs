import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import YAML from "yaml";

import { validateDelivery } from "./validate-delivery.mjs";

const sourceRoot = path.resolve(import.meta.dirname, "..");

function copyDeliveryFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "media-finder-delivery-"));
  for (const entry of [".github", "docs", "tests"]) {
    fs.cpSync(path.join(sourceRoot, entry), path.join(root, entry), { recursive: true });
  }
  for (const entry of [
    "packages/builtin-ui/tests",
    "packages/module-sdk/tests",
    "packages/modules/download-qbittorrent/tests",
    "packages/modules/metadata-manual/tests",
    "packages/modules/metadata-tmdb/tests",
    "packages/modules/release-prowlarr/tests",
  ]) {
    const target = path.join(root, entry);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.cpSync(path.join(sourceRoot, entry), target, { recursive: true });
  }
  for (const entry of [
    "packages/modules/download-qbittorrent/src/media_finder_download_qbittorrent/module.toml",
    "packages/modules/metadata-manual/src/media_finder_metadata_manual/module.toml",
    "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb/module.toml",
    "packages/modules/release-prowlarr/src/media_finder_release_prowlarr/module.toml",
  ]) {
    const target = path.join(root, entry);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.copyFileSync(path.join(sourceRoot, entry), target);
  }
  fs.mkdirSync(path.join(root, "scripts"));
  fs.copyFileSync(
    path.join(sourceRoot, "scripts/smoke-container.sh"),
    path.join(root, "scripts/smoke-container.sh"),
  );
  fs.copyFileSync(
    path.join(sourceRoot, "scripts/verify-image.py"),
    path.join(root, "scripts/verify-image.py"),
  );
  for (const entry of ["Dockerfile", "compose.example.yaml", "README.md"]) {
    fs.copyFileSync(path.join(sourceRoot, entry), path.join(root, entry));
  }
  return root;
}

function mutate(root, relativePath, transform) {
  const target = path.join(root, relativePath);
  fs.writeFileSync(target, transform(fs.readFileSync(target, "utf8")), "utf8");
}

function mutateYaml(root, relativePath, transform) {
  const target = path.join(root, relativePath);
  const value = YAML.parse(fs.readFileSync(target, "utf8"));
  const transformed = transform(value) ?? value;
  fs.writeFileSync(target, YAML.stringify(transformed), "utf8");
}

const validationDate = "2026-08-28";

function validSecurityException(overrides = {}) {
  return {
    id: "security-exception-example",
    scanner: "ruff",
    finding_id: "S101",
    severity: "medium",
    scope: "packages/core/src/example.py:10",
    disposition: "false-positive",
    rationale: "The bounded test fixture contains no production assertion.",
    owner: "@maintainer",
    tracking_ref: "https://github.com/hametovbr/media-finder/issues/123",
    approved_on: "2026-08-01",
    expires_on: "2026-10-01",
    suppression: {
      kind: "repository-file",
      path: "config/security-suppressions.txt",
    },
    ...overrides,
  };
}

function writeSecurityManifest(root, exceptions, schemaVersion = 1) {
  const target = path.join(root, ".github/security-exceptions.yaml");
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(
    target,
    YAML.stringify({ schema_version: schemaVersion, exceptions }),
    "utf8",
  );
}

function writeNativeSuppression(root, identifier = "security-exception-example") {
  const target = path.join(root, "config/security-suppressions.txt");
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, `ignored-rule # security-exception: ${identifier}\n`, "utf8");
}

function securityFailures(root) {
  return validateDelivery(root, { currentDate: validationDate }).filter((failure) =>
    failure.startsWith(".github/security-exceptions.yaml:"),
  );
}

function ensureWebQualitySteps(value) {
  if (
    ["pnpm ui:format", "pnpm ui:lint", "pnpm ui:test"].every((command) =>
      value.includes(`run: ${command}`),
    )
  ) {
    return value;
  }
  const anchor = "      - name: Build frontend production assets\n        run: pnpm ui:build\n";
  assert.ok(value.includes(anchor), "missing frontend production build step");
  const steps = [
    "      - name: Check built-in UI formatting",
    "        run: pnpm ui:format",
    "      - name: Lint built-in UI",
    "        run: pnpm ui:lint",
    "      - name: Test built-in UI",
    "        run: pnpm ui:test",
    "",
  ].join("\n");
  return value.replace(anchor, `${steps}${anchor}`);
}

function replaceDockerInstructionWithComment(value, instructionStart) {
  const start = value.indexOf(instructionStart);
  assert.notEqual(start, -1, `missing Docker instruction ${instructionStart}`);
  const end = value.indexOf("\n\nFROM ", start);
  assert.notEqual(end, -1, `missing end of Docker instruction ${instructionStart}`);
  const instruction = value.slice(start, end);
  const commented = instruction.replaceAll("\n", " ");
  return `${value.slice(0, start)}RUN true\n# ${commented}${value.slice(end)}`;
}

function moveBuilderRunToUnusedProofStage(value) {
  const start = value.indexOf("RUN mkdir /wheels");
  assert.notEqual(start, -1, "missing wheel builder instruction");
  const runtimeStage = value.indexOf("\n\nFROM python:3.13.14-slim-bookworm AS runtime", start);
  assert.notEqual(runtimeStage, -1, "missing runtime stage");
  const builderRun = value.slice(start, runtimeStage);
  return `${value.slice(0, start)}RUN true\n\nFROM builder AS unused-proof-stage\n${builderRun}${value.slice(runtimeStage)}`;
}

test("current delivery workflows satisfy the structural contract", () => {
  assert.deepEqual(validateDelivery(sourceRoot), []);
});

test("stable release preparation requires the trusted main-only dispatch workflow", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const workflowPath = path.join(root, ".github/workflows/prepare-release.yaml");
  fs.mkdirSync(path.dirname(workflowPath), { recursive: true });
  fs.writeFileSync(workflowPath, "name: placeholder\n", "utf8");
  fs.rmSync(workflowPath);

  assert.match(
    validateDelivery(root).join("\n"),
    /prepare-release\.yaml: required delivery artifact is missing/,
  );
});

test("stable release preparation accepts only a required canonical version dispatch", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    value.on.push = { branches: ["main"] };
    value.on.workflow_dispatch.inputs.extra = { required: false, type: "string" };
    value.on.workflow_dispatch.inputs.version.required = false;
    value.on.workflow_dispatch.inputs.version.type = "choice";
    return value;
  });

  const failures = validateDelivery(root).join("\n");
  assert.match(failures, /prepare-release\.yaml: stable release preparation must use workflow_dispatch only/);
  assert.match(failures, /prepare-release\.yaml: workflow_dispatch must expose only the version input/);
  assert.match(failures, /prepare-release\.yaml: version input must be a required string/);
});

test("stable release preparation guards the trusted main ref", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    value.jobs.release.if = "${{ github.ref == 'refs/heads/main' }}";
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /prepare-release\.yaml: controller job must guard workflow_dispatch on main/,
  );
});

test("stable release preparation serializes requests without cancelling runs", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    value.concurrency.group = "release-controller-${{ inputs.version }}";
    value.concurrency["cancel-in-progress"] = true;
    return value;
  });

  const failures = validateDelivery(root).join("\n");
  assert.match(failures, /prepare-release\.yaml: controller concurrency must use the constant repository-wide group/);
  assert.match(failures, /prepare-release\.yaml: controller concurrency must not cancel in-progress runs/);
});

test("stable release preparation keeps its bounded controller timeout", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    value.jobs.release["timeout-minutes"] = 30;
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /prepare-release\.yaml: controller job must have a 330-minute timeout/,
  );
});

test("stable release preparation keeps the workflow token least-privileged", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    value.permissions = {
      actions: "read",
      contents: "write",
      "pull-requests": "write",
      administration: "write",
      checks: "write",
    };
    value.jobs.release.permissions = { contents: "write", actions: "write" };
    return value;
  });

  const failures = validateDelivery(root).join("\n");
  assert.match(failures, /prepare-release\.yaml: workflow token permissions must be limited to actions read and contents read/);
  assert.match(failures, /prepare-release\.yaml: controller job permissions must remain read-only/);
});

test("stable release preparation checks out the trusted revision without persisted credentials", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    const checkout = value.jobs.release.steps.find((step) =>
      String(step.uses ?? "").startsWith("actions/checkout@"),
    );
    checkout.with.ref = "${{ inputs.version }}";
    checkout.with["fetch-depth"] = 1;
    checkout.with["persist-credentials"] = true;
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /prepare-release\.yaml: trusted checkout must use github\.sha, complete history, and no persisted credentials/,
  );
});

test("stable release preparation pins its complete toolchain and freezes installs", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    const steps = value.jobs.release.steps;
    steps.find((step) => String(step.uses ?? "").startsWith("actions/setup-python@")).with[
      "python-version"
    ] = "3.12";
    steps.find((step) => String(step.uses ?? "").startsWith("actions/setup-node@")).with[
      "node-version"
    ] = "20";
    steps.find((step) => String(step.uses ?? "").startsWith("astral-sh/setup-uv@")).with.version = "0.11.0";
    steps.find((step) => String(step.uses ?? "").startsWith("pnpm/action-setup@")).with.version = "10.0.0";
    steps.find((step) => step.name === "Install locked Python workspace").run = "uv sync";
    steps.find((step) => step.name === "Install locked Node workspace").run = "pnpm install";
    return value;
  });

  const failures = validateDelivery(root).join("\n");
  assert.match(failures, /prepare-release\.yaml: controller must use the pinned Python 3\.13 toolchain/);
  assert.match(failures, /prepare-release\.yaml: controller must use the pinned Node 24 toolchain/);
  assert.match(failures, /prepare-release\.yaml: controller must use the pinned uv 0\.12\.5 toolchain/);
  assert.match(failures, /prepare-release\.yaml: controller must use the pinned pnpm toolchain/);
  assert.match(failures, /prepare-release\.yaml: frozen Python and Node installs must complete before credentials are exposed/);
});

test("stable release preparation pins the github-script controller action", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    const controller = value.jobs.release.steps.find((step) => step.name === "Request stable release");
    controller.uses = "actions/github-script@v8";
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /prepare-release\.yaml: release must pin actions\/github-script@v8 to an immutable 40-character commit SHA/,
  );
});

test("stable release preparation confines App credentials to its final controller step", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    value.jobs.release.env = { RELEASE_APP_PRIVATE_KEY: "${{ secrets.RELEASE_APP_PRIVATE_KEY }}" };
    const setup = value.jobs.release.steps.find((step) => step.name === "Install locked Node workspace");
    setup.env = { RELEASE_APP_CLIENT_ID: "${{ vars.RELEASE_APP_CLIENT_ID }}" };
    const controller = value.jobs.release.steps.find((step) => step.name === "Request stable release");
    controller.env.EXTRA_TOKEN = "${{ secrets.EXTRA_TOKEN }}";
    return value;
  });

  const failures = validateDelivery(root).join("\n");
  assert.match(failures, /prepare-release\.yaml: credentials must not be configured at job scope/);
  assert.match(failures, /prepare-release\.yaml: candidate and setup steps must not receive release credentials/);
  assert.match(failures, /prepare-release\.yaml: App credentials must be confined to the final controller environment/);
});

test("stable release preparation invokes the fixed request command without shell interpolation", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/prepare-release.yaml", (value) => {
    const controller = value.jobs.release.steps.find((step) => step.name === "Request stable release");
    controller.with.script = "await exec.exec(`node scripts/release-automation.mjs --phase request --version ${{ inputs.version }}`);";
    return value;
  });

  const failures = validateDelivery(root).join("\n");
  assert.match(failures, /prepare-release\.yaml: controller must invoke the fixed request command with an argument array/);
  assert.match(failures, /prepare-release\.yaml: controller script must not interpolate inputs or invoke a shell/);
});

test("stable release preparation executes its injected command with the version argument", async (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const workflow = YAML.parse(
    fs.readFileSync(path.join(root, ".github/workflows/prepare-release.yaml"), "utf8"),
  );
  const controller = workflow.jobs.release.steps.find((step) => step.name === "Request stable release");
  const calls = [];
  const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
  const processFixture = { env: { RELEASE_VERSION: "0.5.0" } };
  const execFixture = {
    exec: async (...arguments_) => {
      calls.push(arguments_);
      return 0;
    },
  };

  await new AsyncFunction("exec", "process", controller.with.script)(execFixture, processFixture);

  assert.deepEqual(calls, [
    [
      "node",
      ["scripts/release-automation.mjs", "--phase", "request", "--version", "0.5.0"],
      { env: processFixture.env },
    ],
  ]);
});

test("floating third-party action refs are rejected", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(/actions\/checkout@[0-9a-f]{40}/, "actions/checkout@v4"),
  );

  assert.match(validateDelivery(root).join("\n"), /immutable 40-character commit SHA/);
});

test("edge publication requires the reusable verification job", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/ci.yaml", (value) =>
    value.replace("needs: verification", "needs: []"),
  );

  assert.match(validateDelivery(root).join("\n"), /edge publish job must need verification/);
});

test("edge publication is restricted to main push events", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/ci.yaml", (value) =>
    value.replace(
      "github.event_name == 'push' && github.ref == 'refs/heads/main'",
      "github.ref == 'refs/heads/main'",
    ),
  );

  assert.match(validateDelivery(root).join("\n"), /edge publish condition must be main push only/);
});

test("stable publication requires verification of the release commit", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    value.jobs.publish.needs = [];
    return value;
  });

  assert.match(validateDelivery(root).join("\n"), /stable publish job must need verification/);
});

test("stable publication is restricted to published release events", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    value.on.release.types = ["published", "created"];
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /stable publishing must use published releases and one manual entry point/,
  );
});

test("the manual publication entry point accepts exactly one required tag input", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    value.on.workflow_dispatch.inputs.confirm = { required: false, type: "boolean" };
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /manual publication entry point must accept exactly one required tag input/,
  );
});

test("the manual publication job is main-only", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    value.jobs.repair.if = "${{ github.event_name == 'workflow_dispatch' }}";
    return value;
  });

  assert.match(validateDelivery(root).join("\n"), /manual publication must be main-only/);
});

test("the manual publication job must resolve and validate the release before publishing", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    value.jobs.repair.steps = value.jobs.repair.steps.filter(
      (step) => step.id !== "resolve",
    );
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /manual publication must resolve and validate the requested stable release/,
  );
});

test("the manual publication job takes the publisher from the trusted dispatch revision", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    const trusted = value.jobs.repair.steps.find(
      (step) => step.with?.path !== undefined && step.uses?.startsWith("actions/checkout@"),
    );
    trusted.with.ref = "${{ steps.resolve.outputs.revision }}";
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /manual publication must obtain the publisher from the trusted dispatch revision/,
  );
});

test("the manual publication job pins the resolved release identity", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    const publisher = value.jobs.repair.steps.find(
      (step) => step.name === "Publish and verify stable image",
    );
    publisher.env.GITHUB_SHA = "${{ github.sha }}";
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /manual publication must pin the resolved stable release identity/,
  );
});

test("stable publication serializes every release and keeps waiting runs", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    value.concurrency = {
      group: "stable-container-${{ github.event.release.tag_name }}",
      "cancel-in-progress": true,
    };
    return value;
  });

  const failures = validateDelivery(root).join("\n");
  assert.match(failures, /stable publication concurrency group must serialize every release/);
  assert.match(failures, /stable publication concurrency must not cancel in-progress releases/);
});

test("stable publication keeps package write access on the gated publisher only", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    value.jobs.verification.permissions = { contents: "read", packages: "write" };
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /stable verification job must not receive package write permission/,
  );
});

test("stable publication does not pass private credentials into the publisher script", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    const publish = value.jobs.publish.steps.find((step) => step.name === "Publish and verify stable image");
    publish.env.RELEASE_APP_PRIVATE_KEY = "${{ secrets.RELEASE_APP_PRIVATE_KEY }}";
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /stable publisher must not expose credentials to the publication script/,
  );
});

test("stable publication checks out the release event revision with complete history", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    const checkout = value.jobs.publish.steps.find((step) =>
      String(step.uses ?? "").startsWith("actions/checkout@"),
    );
    checkout.with.ref = "${{ github.event.release.tag_name }}";
    return value;
  });

  assert.match(validateDelivery(root).join("\n"), /stable publisher checkout must use the release event revision/);
});

test("stable publication executes the gated verifier script", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    const publish = value.jobs.publish.steps.find((step) => step.name === "Publish and verify stable image");
    publish.run = "docker buildx build --push .";
    return value;
  });

  const failures = validateDelivery(root).join("\n");
  assert.match(failures, /stable publisher must execute scripts\/release-publication\.mjs/);
});

test("documentation verification executes release automation script tests explicitly", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/verify.yaml", (value) => {
    value.jobs.documentation.steps = value.jobs.documentation.steps.filter(
      (step) => step.name !== "Test release automation scripts",
    );
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /documentation job must run release-publication\.test\.mjs and release-automation\.test\.mjs/,
  );
});

test("stable publication rejects the obsolete direct Docker publisher contract", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateYaml(root, ".github/workflows/release.yaml", (value) => {
    value.jobs.publish.steps.push({
      uses: "docker/build-push-action@10e90e3645eae34f1e60eeb005ba3a3d33f178e8",
      with: { push: true },
    });
    return value;
  });

  assert.match(
    validateDelivery(root).join("\n"),
    /stable publisher must not use a direct Docker build or metadata action/,
  );
});

test("image smoke test must exercise every public and protected surface", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "scripts/smoke-container.sh", (value) =>
    value.replace("/health/live", "/health/omitted"),
  );

  assert.match(validateDelivery(root).join("\n"), /image smoke test must validate \/health\/live/);
});

test("all exact first-party integration variables are required in deployment artifacts", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "compose.example.yaml", (value) =>
    value.replace(/^\s+QBITTORRENT_PASSWORD:.*\n/m, ""),
  );

  assert.match(validateDelivery(root).join("\n"), /QBITTORRENT_PASSWORD/);
});

test("compose integration variables follow statically selected module manifests", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(
    root,
    "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb/module.toml",
    (value) => value.replace('name = "TMDB_TOKEN"', 'name = "TMDB_ACCESS_TOKEN"'),
  );

  assert.match(validateDelivery(root).join("\n"), /TMDB_ACCESS_TOKEN/);
});

test("operator environment table follows manifest classifications", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(
    root,
    "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb/module.toml",
    (value) => value.replace("secret = true", "secret = false"),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /module environment documentation must match first-party manifests/,
  );
});

test("configuration-free modules are explicit in manifest-derived documentation", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(
    root,
    "packages/modules/metadata-manual/src/media_finder_metadata_manual/module.toml",
    (value) =>
      `${value}\n[[environment]]\nname = "MANUAL_TOKEN"\nrequired = true\nsecret = true\ndescription_key = "module.manual.environment.token"\n`,
  );

  assert.match(validateDelivery(root).join("\n"), /MANUAL_TOKEN/);
});

test("operator environment table cannot omit a manifest declaration", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "docs/operations.md", (value) =>
    value.replace(/^\| `qbittorrent` \| `download-client` \| `QBITTORRENT_PASSWORD`.*\n/m, ""),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /module environment documentation must match first-party manifests/,
  );
});

test("compose must keep the built-in UI enabled by default", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "compose.example.yaml", (value) =>
    value.replace("${MEDIA_FINDER_UI_MODE:-builtin}", "disabled"),
  );

  assert.match(validateDelivery(root).join("\n"), /MEDIA_FINDER_UI_MODE/);
});

test("verification must build both independently replaceable UI boundary wheels", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("--package media-finder-builtin-ui", "--package omitted-ui"),
  );

  assert.match(validateDelivery(root).join("\n"), /wheel build is missing media-finder-builtin-ui/);
});

test("frontend assets must be built before the built-in UI wheel", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(
      "      - name: Build frontend production assets\n        run: pnpm ui:build\n",
      "",
    ),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /frontend production build must run before workspace wheels/,
  );
});

for (const [label, command, expected] of [
  ["formatting", "pnpm ui:format", /python job must run pnpm ui:format/],
  ["linting", "pnpm ui:lint", /python job must run pnpm ui:lint/],
  ["unit tests", "pnpm ui:test", /python job must run pnpm ui:test/],
]) {
  test(`web quality verification requires built-in UI ${label}`, (context) => {
    const root = copyDeliveryFixture();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    mutate(root, ".github/workflows/verify.yaml", (value) =>
      ensureWebQualitySteps(value).replace(`run: ${command}`, "run: node --version"),
    );

    assert.match(validateDelivery(root).join("\n"), expected);
  });
}

test("the production runtime image cannot contain a Node runtime", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "Dockerfile", (value) =>
    value.replace(
      "FROM python:3.13.14-slim-bookworm AS runtime",
      "FROM node:24-bookworm-slim AS runtime",
    ),
  );

  assert.match(validateDelivery(root).join("\n"), /runtime image must remain Python-only/);
});

test("verification must run built-in UI tests through the wheel-only isolation runner", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(
      "packages/builtin-ui/tests/run_isolated.py unit",
      "packages/builtin-ui/tests/test_fake_gateway.py",
    ),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /unit job must run the wheel-only built-in UI suite/,
  );
});

test("browser verification must run the Playwright built-in UI suite", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("pnpm ui:browser", "pnpm ui:test"),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /browser job must run the Playwright built-in UI suite/,
  );
});

test("browser evidence upload is required", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(/\n      - name: Upload browser evidence[\s\S]*?(?=\n  [a-z]|\n$)/, ""),
  );

  assert.match(validateDelivery(root).join("\n"), /browser job must upload browser evidence/);
});

test("browser evidence upload action must use the approved immutable pin", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(/actions\/upload-artifact@[0-9a-f]{40}/, "actions/upload-artifact@v4"),
  );

  assert.match(validateDelivery(root).join("\n"), /approved immutable upload-artifact SHA/);
});

test("browser evidence upload runs after failed browser assertions", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("if: ${{ always() }}\n        uses: actions/upload-artifact", "uses: actions/upload-artifact"),
  );

  assert.match(validateDelivery(root).join("\n"), /browser evidence upload must run with always\(\)/);
});

test("browser evidence upload keeps the declared outputs for seven days", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value
      .replace("retention-days: 7", "retention-days: 30")
      .replace("packages/builtin-ui/web/browser-evidence/results", "packages/builtin-ui/web/browser-evidence/omitted"),
  );

  const failures = validateDelivery(root).join("\n");
  assert.match(failures, /browser evidence upload must retain artifacts for seven days/);
  assert.match(failures, /browser evidence upload paths must be the declared report, results, and provenance outputs/);
});

test("browser evidence upload fails when a declared output is missing", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("if-no-files-found: error", "if-no-files-found: warn"),
  );

  assert.match(validateDelivery(root).join("\n"), /browser evidence upload must fail when required evidence is missing/);
});

test("browser failures cannot be masked while collecting evidence", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("id: browser-tests\n        run: pnpm ui:browser", "id: browser-tests\n        continue-on-error: true\n        run: pnpm ui:browser"),
  );

  assert.match(validateDelivery(root).join("\n"), /browser test failure must not be masked/);
});

test("browser evidence steps reject dynamic failure masking", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value
      .replace("id: browser-tests\n        run", "id: browser-tests\n        continue-on-error: ${{ true }}\n        run")
      .replace("- name: Generate browser evidence\n        if", "- name: Generate browser evidence\n        continue-on-error: ${{ true }}\n        if")
      .replace("- name: Upload browser evidence\n        if", "- name: Upload browser evidence\n        continue-on-error: ${{ true }}\n        if"),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /browser evidence steps must not mask failures with continue-on-error/,
  );
});

test("browser evidence steps preserve browser, provenance, and upload order", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value
      .replace("- name: Generate browser evidence", "- name: temporary browser evidence step")
      .replace("- name: Upload browser evidence", "- name: Generate browser evidence")
      .replace("- name: temporary browser evidence step", "- name: Upload browser evidence"),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /browser tests, provenance, and upload must run in that order/,
  );
});

test("browser evidence keeps read-only repository permissions", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("  browser:\n    runs-on: ubuntu-latest", "  browser:\n    permissions:\n      contents: write\n    runs-on: ubuntu-latest"),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /browser evidence must preserve read-only repository permissions/,
  );
});

test("browser evidence provenance records the browser test outcome", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("BROWSER_TEST_OUTCOME: ${{ steps.browser-tests.outcome }}", "BROWSER_TEST_OUTCOME: success"),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /browser evidence provenance must run after browser tests with their outcome/,
  );
});

test("browser evidence provenance records exact event and pull-request commits", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value
      .replace("MF_EVENT_SHA: ${{ github.sha }}", "MF_EVENT_SHA: ${{ github.ref }}")
      .replace("MF_PR_HEAD_SHA: ${{ github.event.pull_request.head.sha }}", "MF_PR_HEAD_SHA: omitted")
      .replace("MF_PR_BASE_SHA: ${{ github.event.pull_request.base.sha }}", "MF_PR_BASE_SHA: omitted"),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /browser evidence provenance must record the exact event and pull-request commit expressions/,
  );
});

test("real browser-control conformance remains in the contract job", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(
      "tests/test_control_conformance_real.py",
      "tests/test_control_gateway_contract.py",
    ),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /contract job must run real browser-control conformance/,
  );
});

test("serialized module conformance remains in the contract job", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("pnpm module-conformance:validate", "node --version"),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /contract job must validate serialized module conformance independently/,
  );
});

test("image smoke must prove disabled mode retains the control API", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "scripts/smoke-container.sh", (value) =>
    value.replace("MEDIA_FINDER_UI_MODE=disabled", "MEDIA_FINDER_UI_MODE=omitted"),
  );

  assert.match(validateDelivery(root).join("\n"), /disabled UI mode/);
});

test("production image must build every workspace package as a wheel", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "Dockerfile", (value) =>
    value.replace("media-finder-download-qbittorrent \\\n", "omitted-download-client \\\n"),
  );

  assert.match(validateDelivery(root).join("\n"), /build every workspace package as wheels/);
});

test("production image must install only the built wheels into a fresh runtime venv", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "Dockerfile", (value) =>
    value.replace("--no-deps /wheels/*.whl", "--no-deps /build/apps/server"),
  );

  assert.match(validateDelivery(root).join("\n"), /install every workspace wheel into a fresh runtime venv/);
});

test("production image must prove the lock is current and external artifacts remain hash pinned", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "Dockerfile", (value) =>
    value.replace("uv export --locked", "uv export --frozen --no-hashes"),
  );

  assert.match(validateDelivery(root).join("\n"), /locked requirements with hashes/);
});

test("production image must require hashes while installing external requirements", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "Dockerfile", (value) =>
    value.replace("--require-hashes -r /tmp/runtime-requirements.txt", "-r /tmp/runtime-requirements.txt"),
  );

  assert.match(validateDelivery(root).join("\n"), /locked requirements with hashes/);
});

test("commented Docker build instructions cannot satisfy the wheel-only image contract", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "Dockerfile", (value) => replaceDockerInstructionWithComment(value, "RUN mkdir /wheels"));

  assert.match(validateDelivery(root).join("\n"), /build every workspace package as wheels/);
});

test("an unused Docker stage cannot satisfy the runtime venv dataflow contract", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "Dockerfile", moveBuilderRunToUnusedProofStage);

  assert.match(validateDelivery(root).join("\n"), /build every workspace package as wheels/);
});

test("production image verifier file is required", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.rmSync(path.join(root, "scripts/verify-image.py"));

  assert.match(validateDelivery(root).join("\n"), /scripts\/verify-image\.py: required delivery artifact is missing/);
});

test("production smoke must execute the standalone image verifier", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "scripts/smoke-container.sh", (value) =>
    value.replace("python -I - < scripts/verify-image.py", "python -I - < scripts/omitted.py"),
  );

  assert.match(validateDelivery(root).join("\n"), /must execute scripts\/verify-image\.py/);
});

test("verification workflow must execute image verifier tests", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("tests/test_verify_image.py", "tests/omitted_verify_image.py"),
  );

  assert.match(validateDelivery(root).join("\n"), /must execute tests\/test_verify_image\.py/);
});

for (const [label, from, to, expected] of [
  ["runtime user", "USER 10001:10001", "USER root", /runtime must use UID\/GID 10001/],
  [
    "runtime entrypoint",
    '["python", "-m", "media_finder_server"]',
    '["python", "-m", "omitted_server"]',
    /runtime entrypoint must gate startup/,
  ],
]) {
  test(`production image must retain its ${label} invariant`, (context) => {
    const root = copyDeliveryFixture();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    mutate(root, "Dockerfile", (value) => value.replace(from, to));

    assert.match(validateDelivery(root).join("\n"), expected);
  });
}

test("production image must copy the venv from its wheel-builder stage", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "Dockerfile", (value) =>
    value.replace("--from=builder /opt/venv /opt/venv", "--from=builder /opt/venv /app/venv"),
  );

  assert.match(validateDelivery(root).join("\n"), /install every workspace wheel into a fresh runtime venv/);
});

for (const distribution of [
  "media-finder",
  "media-finder-core",
  "media-finder-module-sdk",
  "media-finder-control-contracts",
  "media-finder-builtin-ui",
  "media-finder-metadata-manual",
  "media-finder-metadata-tmdb",
  "media-finder-release-prowlarr",
  "media-finder-download-qbittorrent",
]) {
  test(`verification builds the ${distribution} wheel`, (context) => {
    const root = copyDeliveryFixture();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    mutate(root, ".github/workflows/verify.yaml", (value) =>
      value.replace(`--package ${distribution}`, `--package omitted-${distribution}`),
    );

    assert.match(validateDelivery(root).join("\n"), new RegExp(`wheel build is missing ${distribution}`));
  });
}

for (const suite of ["tests/core", "tests/server", "tests/characterization"]) {
  test(`verification includes the nested ${suite} suite`, (context) => {
    const root = copyDeliveryFixture();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    mutate(root, ".github/workflows/verify.yaml", (value) =>
      value.replace(suite, `${suite}-omitted`),
    );

    assert.match(
      validateDelivery(root).join("\n"),
      new RegExp(`required pytest suite ${suite.replace("/", "\\/")} is missing`),
    );
  });
}

for (const [stepName, expected] of [
  ["Metadata provider conformance", "metadata provider conformance"],
  ["Release provider conformance", "release provider conformance"],
  ["Download client conformance", "download client conformance"],
  ["Manifest and SDK schema drift", "manifest and SDK schema drift"],
  ["Serialized module fixture drift", "serialized module fixture drift"],
  ["Control and processor OpenAPI drift", "control and processor OpenAPI drift"],
  ["Clean migration and schema drift", "clean migration and schema drift"],
]) {
  test(`${stepName} remains a visible verification step`, (context) => {
    const root = copyDeliveryFixture();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    mutate(root, ".github/workflows/verify.yaml", (value) =>
      value.replace(`name: ${stepName}`, `name: Omitted ${stepName}`),
    );

    assert.match(validateDelivery(root).join("\n"), new RegExp(`${expected}.*required`, "i"));
  });
}

test("verification rejects listed pytest paths that do not exist", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("tests/test_db.py", "tests/missing/test_db.py"),
  );

  assert.match(validateDelivery(root).join("\n"), /listed pytest path does not exist/);
});

test("image smoke must prove the built-in UI mode", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "scripts/smoke-container.sh", (value) =>
    value.replace('assert_response "UI root" "$base_url/"', 'assert_response "Omitted root" "$base_url/"'),
  );

  assert.match(validateDelivery(root).join("\n"), /image smoke test must validate UI root/);
});

test("verification preserves exactly the seven protected job identifiers", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    `${value}\n  accidental-eighth-context:\n    runs-on: ubuntu-latest\n    steps: []\n`,
  );

  assert.match(validateDelivery(root).join("\n"), /exactly the seven protected job identifiers/);
});

test("verification seeds the repository-local cache used by offline isolation runners", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(
      "UV_CACHE_DIR: ${{ github.workspace }}/.tools/uv-cache",
      "UV_CACHE_DIR: /tmp/unshared-uv-cache",
    ),
  );

  assert.match(validateDelivery(root).join("\n"), /repository-local uv cache/);
});

test("test paths printed by a no-op command do not count as executed", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace("uv run pytest\n          tests/core", "echo tests/core"),
  );

  assert.match(validateDelivery(root).join("\n"), /required pytest suite tests\/core is missing/);
});

test("named conformance steps must execute pytest rather than echo expected strings", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(
      "run: uv run pytest --no-cov packages/modules/release-prowlarr/tests",
      "run: echo uv run pytest --no-cov packages/modules/release-prowlarr/tests",
    ),
  );

  assert.match(validateDelivery(root).join("\n"), /release provider conformance.*required/i);
});

test("schema drift must execute the Alembic checker rather than echo it", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(
      "uv run python scripts/check_schema_drift.py &&",
      "echo uv run python scripts/check_schema_drift.py &&",
    ),
  );

  assert.match(validateDelivery(root).join("\n"), /clean migration and schema drift.*required/i);
});

test("isolated UI runner must discover future test files recursively", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "packages/builtin-ui/tests/run_isolated.py", (value) =>
    value.replace(
      'sorted(TESTS.rglob("test_*.py"))',
      '(TESTS / "test_fake_gateway.py", TESTS / "test_html_contract.py", TESTS / "test_browser.py")',
    ),
  );

  assert.match(validateDelivery(root).join("\n"), /UI isolation runner must discover test files/);
});

test("security exception manifest is a required delivery artifact", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.rmSync(path.join(root, ".github/security-exceptions.yaml"), { force: true });

  assert.match(securityFailures(root).join("\n"), /required delivery artifact is missing/);
});

test("an empty version-1 security exception manifest is valid", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeSecurityManifest(root, []);

  assert.deepEqual(securityFailures(root), []);
});

test("unknown security exception manifest versions are rejected", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeSecurityManifest(root, [], 2);

  assert.match(securityFailures(root).join("\n"), /schema_version must be 1/);
});

test("security exception manifest entries must be an array", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const target = path.join(root, ".github/security-exceptions.yaml");
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, "schema_version: 1\nexceptions: invalid\n", "utf8");

  assert.match(securityFailures(root).join("\n"), /exceptions must be an array/);
});

test("malformed security exception YAML does not expose its source line", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const target = path.join(root, ".github/security-exceptions.yaml");
  fs.writeFileSync(
    target,
    "schema_version: 1\nexceptions: [MUST-NOT-BE-EMITTED\n",
    "utf8",
  );

  const failures = securityFailures(root).join("\n");
  assert.match(failures, /invalid YAML/);
  assert.doesNotMatch(failures, /MUST-NOT-BE-EMITTED/);
});

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
  "suppression",
]) {
  test(`security exceptions require ${field}`, (context) => {
    const root = copyDeliveryFixture();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    writeNativeSuppression(root);
    const exception = validSecurityException();
    delete exception[field];
    writeSecurityManifest(root, [exception]);

    const label = field === "id" ? "exception\\[0\\]" : "security-exception-example";
    assert.match(securityFailures(root).join("\n"), new RegExp(`${label}.*${field}`));
  });
}

test("security exception identifiers use stable kebab-case", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root, "MUST-NOT-BE-EMITTED");
  writeSecurityManifest(root, [validSecurityException({ id: "MUST-NOT-BE-EMITTED" })]);

  const failures = securityFailures(root).join("\n");
  assert.match(failures, /exception\[0\].*stable kebab-case/);
  assert.doesNotMatch(failures, /MUST-NOT-BE-EMITTED/);
});

test("security exception tracking references use safe GitHub identifiers", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [
    validSecurityException({ tracking_ref: "https://example.com/private/report" }),
  ]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*tracking_ref/);
});

for (const [field, value] of [
  ["severity", "urgent"],
  ["disposition", "permanent-ignore"],
]) {
  test(`security exceptions reject invalid ${field}`, (context) => {
    const root = copyDeliveryFixture();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    writeNativeSuppression(root);
    writeSecurityManifest(root, [validSecurityException({ [field]: value })]);

    assert.match(securityFailures(root).join("\n"), new RegExp(`security-exception-example.*${field}`));
  });
}

test("security exception identifiers are unique", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [validSecurityException(), validSecurityException()]);

  assert.match(securityFailures(root).join("\n"), /duplicate id security-exception-example/);
});

for (const unsafePath of ["/etc/passwd", "../outside.txt"]) {
  test(`repository suppression paths reject ${unsafePath}`, (context) => {
    const root = copyDeliveryFixture();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    writeSecurityManifest(root, [
      validSecurityException({
        suppression: { kind: "repository-file", path: unsafePath },
      }),
    ]);

    assert.match(securityFailures(root).join("\n"), /security-exception-example.*suppression\.path/);
  });
}

test("the exception manifest cannot act as its own native suppression", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeSecurityManifest(root, [
    validSecurityException({
      suppression: { kind: "repository-file", path: ".github/security-exceptions.yaml" },
    }),
  ]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*manifest/);
});

test("a symlink to the exception manifest cannot act as a native suppression", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeSecurityManifest(root, [validSecurityException()]);
  const target = path.join(root, "config/security-suppressions.txt");
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.symlinkSync("../.github/security-exceptions.yaml", target);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*manifest/);
});

test("repository suppressions cannot escape the checkout through a symlink", (context) => {
  const root = copyDeliveryFixture();
  const externalRoot = fs.mkdtempSync(path.join(os.tmpdir(), "media-finder-external-suppression-"));
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  context.after(() => fs.rmSync(externalRoot, { recursive: true, force: true }));
  const externalTarget = path.join(externalRoot, "security-suppressions.txt");
  fs.writeFileSync(externalTarget, "ignored-rule # security-exception-example\n", "utf8");
  const target = path.join(root, "config/security-suppressions.txt");
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.symlinkSync(externalTarget, target);
  writeSecurityManifest(root, [validSecurityException()]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*inside the checkout/);
});

test("repository suppressions must reference an existing file", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeSecurityManifest(root, [validSecurityException()]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*target is missing/);
});

test("repository suppressions must carry their exception marker", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root, "another-exception");
  writeSecurityManifest(root, [validSecurityException()]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*marker is missing/);
});

test("repository suppression markers require the namespaced form", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const target = path.join(root, "config/security-suppressions.txt");
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, "ignored-rule # security-exception-example\n", "utf8");
  writeSecurityManifest(root, [validSecurityException()]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*marker is missing/);
});

test("repository suppression markers do not accept identifier prefixes", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root, "security-exception-example-longer");
  writeSecurityManifest(root, [validSecurityException()]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*marker is missing/);
});

test("security exceptions reject approval dates after expiry", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [validSecurityException({ expires_on: "2026-07-31" })]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*expires_on.*approved_on/);
});

test("security exceptions reject blank required text", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [validSecurityException({ rationale: "   " })]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*rationale/);
});

test("security exceptions reject unbounded required text", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [validSecurityException({ rationale: "x".repeat(2049) })]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*rationale.*2048/);
});

test("security exceptions require exact calendar dates", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [validSecurityException({ approved_on: "2026-02-30" })]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*approved_on.*YYYY-MM-DD/);
});

test("security exceptions cannot exceed the 90-day review window", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [validSecurityException({ expires_on: "2026-10-31" })]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*90 days/);
});

test("security exceptions reject approval dates after the current UTC date", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [
    validSecurityException({ approved_on: "2026-08-29", expires_on: "2026-10-01" }),
  ]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*approved_on.*future/);
});

test("security exceptions expire at the start of their UTC expiry date", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [validSecurityException({ expires_on: validationDate })]);

  assert.match(securityFailures(root).join("\n"), /security-exception-example.*expired/);
});

test("an active repository-file security exception is valid", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  writeNativeSuppression(root);
  writeSecurityManifest(root, [validSecurityException()]);

  assert.deepEqual(securityFailures(root), []);
});

test("an active GitHub-hosted security exception locator is structurally valid", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const alertUrl = "https://github.com/hametovbr/media-finder/security/code-scanning/123";
  writeSecurityManifest(root, [
    validSecurityException({
      id: "security-exception-codeql-example",
      scanner: "codeql",
      finding_id: "js/example-query",
      tracking_ref: alertUrl,
      suppression: { kind: "github-code-scanning-alert", url: alertUrl },
    }),
  ]);

  assert.deepEqual(securityFailures(root), []);
});
