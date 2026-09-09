import { describe, expect, it, vi } from "vitest";

import { createAcquisitionAttempt } from "./acquisition-attempt";

describe("createAcquisitionAttempt", () => {
  it("reuses one idempotency key for retries and creates another for a new confirmation", async () => {
    const submit = vi.fn().mockResolvedValue({ status: "submitted" });
    const randomUUID = vi
      .fn()
      .mockReturnValueOnce("key-1")
      .mockReturnValueOnce("key-2");
    const input = {
      destination: "movies",
      mediaItemId: "item-1",
      releaseToken: "release-1",
    };

    const first = createAcquisitionAttempt(submit, input, randomUUID);
    await first();
    await first();
    const second = createAcquisitionAttempt(submit, input, randomUUID);
    await second();

    expect(
      submit.mock.calls.map(([request]) => request.idempotencyKey),
    ).toEqual(["key-1", "key-1", "key-2"]);
    expect(randomUUID).toHaveBeenCalledTimes(2);
  });

  it("retains an immutable payload snapshot and gives the submitter a fresh request copy", async () => {
    const submit = vi.fn().mockResolvedValue({ status: "submitted" });
    const randomUUID = vi.fn().mockReturnValue("key-1");
    const input = {
      destination: "movies",
      mediaItemId: "item-1",
      releaseToken: "release-1",
    };

    const attempt = createAcquisitionAttempt(submit, input, randomUUID);
    input.destination = "archive";
    await attempt();
    const firstCall = submit.mock.calls[0];
    expect(firstCall).toBeDefined();
    const firstRequest = firstCall![0];
    firstRequest.destination = "mutated-by-callback";
    await attempt();
    const secondCall = submit.mock.calls[1];
    expect(secondCall).toBeDefined();

    expect(firstRequest).toEqual({
      destination: "mutated-by-callback",
      idempotencyKey: "key-1",
      mediaItemId: "item-1",
      releaseToken: "release-1",
    });
    const secondRequest = secondCall![0];
    expect(secondRequest).toEqual({
      destination: "movies",
      idempotencyKey: "key-1",
      mediaItemId: "item-1",
      releaseToken: "release-1",
    });
    expect(secondRequest).not.toBe(firstRequest);
  });
});
