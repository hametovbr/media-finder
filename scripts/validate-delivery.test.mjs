import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { validateDelivery } from "./validate-delivery.mjs";

const sourceRoot = path.resolve(import.meta.dirname, "..");

function copyDeliveryFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "media-finder-delivery-"));
  for (const entry of [".github", "tests", "docs"]) {
    fs.cpSync(path.join(sourceRoot, entry), path.join(root, entry), { recursive: true });
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
