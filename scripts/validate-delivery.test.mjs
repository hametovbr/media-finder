import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { validateDelivery } from "./validate-delivery.mjs";

const sourceRoot = path.resolve(import.meta.dirname, "..");

function copyDeliveryFixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "media-finder-delivery-"));
  for (const entry of [".github", "tests"]) {
    fs.cpSync(path.join(sourceRoot, entry), path.join(root, entry), { recursive: true });
  }
  fs.mkdirSync(path.join(root, "scripts"));
  fs.copyFileSync(
    path.join(sourceRoot, "scripts/smoke-container.sh"),
    path.join(root, "scripts/smoke-container.sh"),
  );
  for (const entry of ["Dockerfile", "compose.example.yaml"]) {
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
