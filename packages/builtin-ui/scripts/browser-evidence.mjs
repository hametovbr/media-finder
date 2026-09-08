import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

export function missingCaptures(filenames) {
  const scenarios = [
    "bootstrap-failure",
    "provider-discovery-failure",
    "metadata-search-failure",
    "metadata-search-empty",
    "release-search-failure",
    "release-search-empty",
    "locale-update-failure",
    "metadata-search-pending",
    "metadata-keyboard-recovery",
  ];
  return scenarios
    .flatMap((scenario) =>
      ["en", "ru"].flatMap((locale) =>
        [360, 1280].map((width) => `${scenario}-${locale}-${width}.png`),
      ),
    )
    .filter((name) => !filenames.includes(name));
}

export function buildProvenance(env, observed) {
  return {
    repository: env.GITHUB_REPOSITORY || null,
    checkoutSha: observed.checkoutSha,
    eventSha: env.MF_EVENT_SHA || env.GITHUB_SHA || null,
    pullRequest: env.MF_PR_HEAD_SHA
      ? {
          headSha: env.MF_PR_HEAD_SHA,
          baseSha: env.MF_PR_BASE_SHA || null,
        }
      : null,
    runId: env.GITHUB_RUN_ID || null,
    runAttempt: env.GITHUB_RUN_ATTEMPT || null,
    testOutcome: env.BROWSER_TEST_OUTCOME || "not-run",
    nodeVersion: process.version,
    playwrightVersion: observed.playwrightVersion,
    browserVersion: observed.browserVersion,
  };
}

if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  const require = createRequire(import.meta.url);
  const root = fileURLToPath(
    new URL("../web/browser-evidence/", import.meta.url),
  );
  const repository = fileURLToPath(new URL("../../../", import.meta.url));
  let browserVersion = null;
  try {
    browserVersion = execFileSync(
      require("@playwright/test").chromium.executablePath(),
      ["--version"],
      {
        encoding: "utf8",
        timeout: 10000,
        stdio: ["ignore", "pipe", "ignore"],
      },
    ).trim();
  } catch {
    /* Setup failure retains partial provenance, never a passing browser claim. */
  }
  const provenance = buildProvenance(process.env, {
    checkoutSha: execFileSync("git", ["rev-parse", "HEAD"], {
      cwd: repository,
      encoding: "utf8",
    }).trim(),
    playwrightVersion: require("@playwright/test/package.json").version,
    browserVersion,
  });
  const filenames = existsSync(`${root}/results`)
    ? readdirSync(`${root}/results`, { recursive: true, withFileTypes: true })
        .filter((entry) => entry.isFile())
        .map((entry) => entry.name)
    : [];
  provenance.missingCaptures = missingCaptures(filenames);
  mkdirSync(root, { recursive: true });
  writeFileSync(
    `${root}/provenance.json`,
    `${JSON.stringify(provenance, null, 2)}\n`,
  );
  if (
    provenance.testOutcome === "success" &&
    (!browserVersion ||
      !existsSync(`${root}/report/index.html`) ||
      provenance.missingCaptures.length)
  ) {
    throw new Error(
      "Successful browser evidence requires browser version, HTML report and all 36 captures",
    );
  }
}
