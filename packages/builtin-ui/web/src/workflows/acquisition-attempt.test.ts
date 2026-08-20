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
});
