import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

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
  fs.mkdirSync(path.join(root, "scripts"));
  fs.copyFileSync(
    path.join(sourceRoot, "scripts/smoke-container.sh"),
    path.join(root, "scripts/smoke-container.sh"),
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

test("current delivery workflows satisfy the structural contract", () => {
  assert.deepEqual(validateDelivery(sourceRoot), []);
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
  mutate(root, ".github/workflows/release.yaml", (value) =>
    value.replace("needs: verification", "needs: []"),
  );

  assert.match(validateDelivery(root).join("\n"), /stable publish job must need verification/);
});

test("stable publication is restricted to published release events", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/release.yaml", (value) =>
    value.replace("types: [published]", "types: [created]"),
  );

  assert.match(validateDelivery(root).join("\n"), /stable publishing must use published releases only/);
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

test("browser verification must run the fake gateway UI from installed wheels", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, ".github/workflows/verify.yaml", (value) =>
    value.replace(
      "packages/builtin-ui/tests/run_isolated.py browser",
      "packages/builtin-ui/tests/test_browser.py",
    ),
  );

  assert.match(
    validateDelivery(root).join("\n"),
    /browser job must run the wheel-only built-in UI suite/,
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

test("production workspace installs cannot retain builder-only editable paths", (context) => {
  const root = copyDeliveryFixture();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutate(root, "Dockerfile", (value) => value.replace(" --no-editable", ""));

  assert.match(validateDelivery(root).join("\n"), /installed non-editably/);
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
