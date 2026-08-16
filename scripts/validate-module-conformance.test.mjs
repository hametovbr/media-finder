import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { validateModuleConformance } from "./validate-module-conformance.mjs";

const sourceRoot = path.resolve(import.meta.dirname, "..");

function copyFixtureTree() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "media-finder-module-conformance-"));
  fs.cpSync(path.join(sourceRoot, "schemas"), path.join(root, "schemas"), { recursive: true });
  fs.mkdirSync(path.join(root, "packages", "modules"), { recursive: true });
  for (const moduleName of [
    "metadata-manual",
    "metadata-tmdb",
    "release-prowlarr",
    "download-qbittorrent",
  ]) {
    const source = path.join(sourceRoot, "packages", "modules", moduleName, "src");
    const destination = path.join(root, "packages", "modules", moduleName, "src");
    fs.cpSync(source, destination, { recursive: true });
  }
  return root;
}

function mutateFixture(root, moduleName, transform) {
  const fixturePath = fs
    .readdirSync(path.join(root, "packages", "modules", moduleName, "src"), {
      recursive: true,
    })
    .map((entry) => String(entry))
    .find((entry) => entry.endsWith(path.join("fixtures", "conformance.json")));
  assert.ok(fixturePath);
  const target = path.join(root, "packages", "modules", moduleName, "src", fixturePath);
  const parsed = JSON.parse(fs.readFileSync(target, "utf8"));
  transform(parsed);
  fs.writeFileSync(target, `${JSON.stringify(parsed, null, 2)}\n`, "utf8");
}

test("all first-party serialized conformance fixtures validate without Python", () => {
  assert.deepEqual(validateModuleConformance(sourceRoot), []);
});

test("manifest identity drift is rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "metadata-manual", (fixture) => {
    fixture.module_id = "drifted";
  });

  assert.match(validateModuleConformance(root).join("\n"), /does not match module.toml/);
});

test("fixture module versions accept the same full SemVer as module manifests", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "metadata-manual", (fixture) => {
    fixture.module_version = "1.2.3-rc.1+build.5";
  });
  const manifest = path.join(
    root,
    "packages/modules/metadata-manual/src/media_finder_metadata_manual/module.toml",
  );
  fs.writeFileSync(
    manifest,
    fs.readFileSync(manifest, "utf8").replace('module_version = "0.1.0"', 'module_version = "1.2.3-rc.1+build.5"'),
    "utf8",
  );
  mutateFixture(root, "metadata-manual", (fixture) => {
    fixture.manifest_sha256 = crypto
      .createHash("sha256")
      .update(fs.readFileSync(manifest))
      .digest("hex");
  });

  assert.deepEqual(validateModuleConformance(root), []);
});

test("raw manifest byte drift is rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const manifest = path.join(
    root,
    "packages/modules/metadata-manual/src/media_finder_metadata_manual/module.toml",
  );
  fs.appendFileSync(manifest, "\n", "utf8");

  assert.match(validateModuleConformance(root).join("\n"), /manifest_sha256 does not match/);
});

test("serialized environment values are rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "metadata-tmdb", (fixture) => {
    fixture.environment[0].value = "must-never-be-serialized";
  });

  assert.match(validateModuleConformance(root).join("\n"), /schema validation failed/);
});

test("private selection bodies are rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "release-prowlarr", (fixture) => {
    fixture.success.results[0].private_selection = "must-never-be-serialized";
  });

  assert.match(validateModuleConformance(root).join("\n"), /schema validation failed/);
});

test("artifact bodies are rejected in favor of safe descriptors", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "download-qbittorrent", (fixture) => {
    fixture.success.artifacts[0].artifact_body = "must-never-be-serialized";
  });

  assert.match(validateModuleConformance(root).join("\n"), /schema validation failed/);
});

test("kind-specific release bounds are enforced beyond shape validation", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "release-prowlarr", (fixture) => {
    fixture.success.query.limit = 1;
  });

  assert.match(validateModuleConformance(root).join("\n"), /release results exceed/);
});

test("magnet descriptors use the public 8192-byte bound", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "release-prowlarr", (fixture) => {
    fixture.success.resolved_artifacts[0].artifact.byte_length = 8193;
  });

  assert.match(validateModuleConformance(root).join("\n"), /schema validation failed/);
});

test("torrent descriptors use the public 20 MiB byte bound", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "release-prowlarr", (fixture) => {
    fixture.success.resolved_artifacts[1].artifact.byte_length = 20 * 1024 * 1024 + 1;
  });

  assert.match(validateModuleConformance(root).join("\n"), /schema validation failed/);
});

test("selection_ref is bounded", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "release-prowlarr", (fixture) => {
    fixture.success.results[0].selection_ref = `selection-${"x".repeat(129)}`;
  });

  assert.match(validateModuleConformance(root).join("\n"), /schema validation failed/);
});

test("resolved artifact selection_ref is bounded", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "release-prowlarr", (fixture) => {
    fixture.success.resolved_artifacts[0].selection_ref = `selection-${"x".repeat(129)}`;
  });

  assert.match(validateModuleConformance(root).join("\n"), /schema validation failed/);
});

for (const [label, sourcePageUrl] of [
  ["public DNS", "https://media.themoviedb.org/releases/fixture-1"],
  ["documented fixture DNS", "https://indexer.example.test/releases/fixture-1"],
  ["public IPv4", "https://8.8.8.8/releases/fixture-1"],
  ["public IPv6", "https://[2606:4700:4700::1111]/releases/fixture-1"],
]) {
  test(`safe normalized source path accepts ${label}`, (context) => {
    const root = copyFixtureTree();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    mutateFixture(root, "release-prowlarr", (fixture) => {
      fixture.success.results[0].snapshot.source_page_url = sourcePageUrl;
    });

    assert.deepEqual(validateModuleConformance(root), []);
  });
}

for (const [label, sourcePageUrl] of [
  ["userinfo", "https://user:pass@indexer.example.test/releases/1"],
  ["query", "https://indexer.example.test/releases/1?passkey=secret"],
  ["fragment", "https://indexer.example.test/releases/1#secret"],
  ["loopback", "http://127.0.0.1/releases/1"],
  ["private", "http://192.168.1.2/releases/1"],
  ["single-label intranet", "http://intranet/releases/1"],
  ["mDNS", "http://printer.local/releases/1"],
  ["localhost suffix", "http://service.localhost/releases/1"],
  ["internal suffix", "http://service.internal/releases/1"],
  ["LAN suffix", "http://nas.lan/releases/1"],
  ["arbitrary test suffix", "http://service.test/releases/1"],
  ["bare synthetic test suffix", "http://example.test/releases/1"],
  ["reserved invalid suffix", "http://service.invalid/releases/1"],
  ["reserved example suffix", "http://service.example/releases/1"],
  ["home suffix", "http://service.home/releases/1"],
  ["home ARPA suffix", "http://service.home.arpa/releases/1"],
  ["documentation IPv4", "http://192.0.2.1/releases/1"],
  ["benchmark IPv4", "http://198.18.0.1/releases/1"],
  ["second documentation IPv4", "http://198.51.100.1/releases/1"],
  ["third documentation IPv4", "http://203.0.113.1/releases/1"],
  ["multicast IPv4", "http://224.0.0.1/releases/1"],
  ["short numeric IPv4", "http://127.1/releases/1"],
  ["octal-like IPv4", "http://0177.0.0.1/releases/1"],
  ["hex-like IPv4", "http://0x7f.0.0.1/releases/1"],
  ["documentation IPv6", "http://[2001:db8::1]/releases/1"],
  ["link-local IPv6", "http://[fe80::1]/releases/1"],
  ["unique-local IPv6", "http://[fc00::1]/releases/1"],
  ["multicast IPv6", "http://[ff02::1]/releases/1"],
  ["wrong scheme", "ftp://media.themoviedb.org/releases/1"],
  ["leading whitespace", " https://media.themoviedb.org/releases/1"],
  ["empty path segment", "https://media.themoviedb.org/releases//1"],
  ["parent path segment", "https://media.themoviedb.org/releases/../private"],
  ["current path segment", "https://media.themoviedb.org/releases/./private"],
  ["empty query", "https://media.themoviedb.org/releases/1?"],
  ["empty fragment", "https://media.themoviedb.org/releases/1#"],
  ["empty userinfo", "https://@media.themoviedb.org/releases/1"],
  ["credential path", "https://indexer.example.test/releases/token-secret"],
]) {
  test(`unsafe ${label} source page is rejected`, (context) => {
    const root = copyFixtureTree();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    mutateFixture(root, "release-prowlarr", (fixture) => {
      fixture.success.results[0].snapshot.source_page_url = sourcePageUrl;
    });

    assert.match(
      validateModuleConformance(root).join("\n"),
      /safe release snapshot|schema validation failed/,
    );
  });
}

test("credential-like GUIDs are rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "release-prowlarr", (fixture) => {
    fixture.success.results[0].snapshot.guid = "credential-token-123";
  });

  assert.match(validateModuleConformance(root).join("\n"), /GUID/);
});

for (const [label, guid] of [
  ["overlong", "x".repeat(256)],
  ["URL-shaped", "https://indexer.example.test/releases/1"],
]) {
  test(`${label} GUIDs are rejected by the canonical snapshot schema`, (context) => {
    const root = copyFixtureTree();
    context.after(() => fs.rmSync(root, { recursive: true, force: true }));
    mutateFixture(root, "release-prowlarr", (fixture) => {
      fixture.success.results[0].snapshot.guid = guid;
    });

    assert.match(validateModuleConformance(root).join("\n"), /schema validation failed/);
  });
}

test("missing-configuration safe details must exactly match manifest declarations", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "release-prowlarr", (fixture) => {
    fixture.missing_configuration.error.safe_details.missing_names = ["PROWLARR_URL"];
  });

  assert.match(validateModuleConformance(root).join("\n"), /missing-configuration case/);
});

test("stable failure operation drift is rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "metadata-tmdb", (fixture) => {
    fixture.stable_failures[0].operation = "wrong-operation";
  });

  assert.match(validateModuleConformance(root).join("\n"), /failure matrix/);
});

test("stable failure code drift is rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "release-prowlarr", (fixture) => {
    fixture.stable_failures[0].error.code = "wrong_code";
  });

  assert.match(validateModuleConformance(root).join("\n"), /failure matrix/);
});

test("credential-shaped arbitrary safe details are rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "metadata-tmdb", (fixture) => {
    fixture.stable_failures[0].error.safe_details = {
      note: "password=must-never-be-public",
    };
  });

  assert.match(validateModuleConformance(root).join("\n"), /sensitive public value/);
});

test("credential-marker values in arbitrary safe details are rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "metadata-tmdb", (fixture) => {
    fixture.stable_failures[0].error.safe_details = {
      reason: "synthetic-secret-value",
    };
  });

  assert.match(validateModuleConformance(root).join("\n"), /sensitive public value/);
});

test("synthetic redaction probes may appear only in their declaration", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "metadata-tmdb", (fixture) => {
    fixture.stable_failures[0].error.safe_details = {
      note: fixture.redaction_probes.credential,
    };
  });

  assert.match(validateModuleConformance(root).join("\n"), /redaction probe leaked/);
});

test("kind-specific exact correlation is enforced beyond shape validation", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  mutateFixture(root, "download-qbittorrent", (fixture) => {
    fixture.success.lookup.correlation = "mf-acq-different";
  });

  assert.match(validateModuleConformance(root).join("\n"), /preserve exact correlation/);
});

test("non-canonical fixture bytes are rejected", (context) => {
  const root = copyFixtureTree();
  context.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const target = fs
    .readdirSync(path.join(root, "packages", "modules", "metadata-manual", "src"), {
      recursive: true,
    })
    .map((entry) => path.join(root, "packages", "modules", "metadata-manual", "src", String(entry)))
    .find((entry) => entry.endsWith(path.join("fixtures", "conformance.json")));
  assert.ok(target);
  fs.appendFileSync(target, "\n", "utf8");

  assert.match(validateModuleConformance(root).join("\n"), /not canonical JSON/);
});
