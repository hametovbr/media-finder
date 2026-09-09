export interface AcquisitionAttemptInput {
  destination: string;
  mediaItemId: string;
  releaseToken: string;
}

export interface AcquisitionAttemptRequest extends AcquisitionAttemptInput {
  idempotencyKey: string;
}

export function createAcquisitionAttempt<Result>(
  submit: (request: AcquisitionAttemptRequest) => Promise<Result>,
  input: AcquisitionAttemptInput,
  randomUUID: () => string = () => crypto.randomUUID(),
): () => Promise<Result> {
  const idempotencyKey = randomUUID();
  const payload = {
    destination: input.destination,
    mediaItemId: input.mediaItemId,
    releaseToken: input.releaseToken,
  };
  return () =>
    submit({
      destination: payload.destination,
      idempotencyKey,
      mediaItemId: payload.mediaItemId,
      releaseToken: payload.releaseToken,
    });
}
