import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ControlClient } from "./control-client";
import { ControlProvider, useControlSession } from "./control-provider";

const session = {
  csrf_token: "csrf-test-token",
  metadata_locale: "en" as const,
  supported_locales: ["en", "ru"] as const,
  ui_locale: "en" as const,
};

function SessionConsumer() {
  const current = useControlSession();
  return <p>{current.ui_locale}</p>;
}

describe("ControlProvider", () => {
  it("bootstraps the session through TanStack Query before rendering children", async () => {
    const client = {
      bootstrapSession: vi.fn().mockResolvedValue(session),
    } as unknown as ControlClient;
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });

    render(
      <QueryClientProvider client={queryClient}>
        <ControlProvider client={client} loadingFallback={<p>loading</p>}>
          <SessionConsumer />
        </ControlProvider>
      </QueryClientProvider>,
    );

    expect(screen.getByText("loading")).toBeInTheDocument();
    expect(await screen.findByText("en")).toBeInTheDocument();
    expect(client.bootstrapSession).toHaveBeenCalledOnce();
  });
});
