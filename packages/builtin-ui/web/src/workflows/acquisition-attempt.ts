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
  return () => submit({ ...input, idempotencyKey });
}
