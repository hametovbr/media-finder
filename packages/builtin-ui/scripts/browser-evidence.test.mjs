import assert from "node:assert/strict";
import { test } from "node:test";
import { buildProvenance, missingCaptures } from "./browser-evidence.mjs";

test("a successful run requires every named locale/viewport capture", () => {
  const expected = missingCaptures([]);
  assert.equal(expected.length, 36);
  assert.deepEqual(missingCaptures(expected), []);
  assert.deepEqual(missingCaptures(expected.slice(1)), [expected[0]]);
  assert.equal(missingCaptures(["unrelated.png"]).length, 36);
});

test("provenance distinguishes checkout from event and PR head/base without copying environment secrets", () => {
  const value = buildProvenance(
    {
      GITHUB_REPOSITORY: "fixture/media-finder",
      GITHUB_SHA: "event",
      MF_EVENT_SHA: "event",
      MF_PR_HEAD_SHA: "head",
      MF_PR_BASE_SHA: "base",
      GITHUB_RUN_ID: "12",
      GITHUB_RUN_ATTEMPT: "2",
      BROWSER_TEST_OUTCOME: "failure",
      SECRET: "not-for-output",
    },
    {
      checkoutSha: "merge",
      playwrightVersion: "pinned",
      browserVersion: "Chromium fixture",
    },
  );
  assert.equal(value.checkoutSha, "merge");
  assert.equal(value.eventSha, "event");
  assert.deepEqual(value.pullRequest, { headSha: "head", baseSha: "base" });
  assert.equal(value.runAttempt, "2");
  assert.equal(value.testOutcome, "failure");
  assert.equal(JSON.stringify(value).includes("not-for-output"), false);
});

test("local execution does not invent hosted identities or passing evidence", () => {
  const value = buildProvenance(
    {},
    { checkoutSha: "local", playwrightVersion: "pinned", browserVersion: null },
  );
  assert.equal(value.runId, null);
  assert.equal(value.pullRequest, null);
  assert.equal(value.testOutcome, "not-run");
  assert.equal(value.browserVersion, null);
});
