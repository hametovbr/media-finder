import {
  focusManager,
  onlineManager,
  QueryClient,
  QueryClientProvider,
} from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider } from "react-i18next";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it, vi } from "vitest";

import type { ControlClient } from "./control-client";
import { ControlProvider, useControlSession } from "./control-provider";
import { createUiI18n } from "../i18n";
import { appRoutes } from "../app-router";

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

  it("renders a safe local error and retries bootstrap once per activation", async () => {
    const client = {
      bootstrapSession: vi
        .fn()
        .mockRejectedValueOnce(new Error("secret payload"))
        .mockResolvedValue(session),
    } as unknown as ControlClient;
    const queryClient = new QueryClient();
    const user = userEvent.setup();

    render(
      <MantineProvider>
        <I18nextProvider i18n={createUiI18n("en")}>
          <QueryClientProvider client={queryClient}>
            <ControlProvider client={client} loadingFallback={<p>loading</p>}>
              <main tabIndex={-1}>ready</main>
            </ControlProvider>
          </QueryClientProvider>
        </I18nextProvider>
      </MantineProvider>,
    );

    expect(
      await screen.findByRole("heading", {
        name: "Could not load Media Finder",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("secret payload")).not.toBeInTheDocument();
    const retry = screen.getByRole("button", { name: "Retry" });
    await user.click(retry);
    await screen.findByText("ready");
    expect(client.bootstrapSession).toHaveBeenCalledTimes(2);
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });

  it("does not issue an automatic bootstrap retry", async () => {
    const client = {
      bootstrapSession: vi.fn().mockRejectedValue(new Error("offline")),
    } as unknown as ControlClient;
    const queryClient = new QueryClient();

    render(
      <MantineProvider>
        <I18nextProvider i18n={createUiI18n("en")}>
          <QueryClientProvider client={queryClient}>
            <ControlProvider client={client}>
              <span>unused</span>
            </ControlProvider>
          </QueryClientProvider>
        </I18nextProvider>
      </MantineProvider>,
    );

    await screen.findByRole("button", { name: "Retry" });
    try {
      await act(async () => {
        focusManager.setFocused(false);
        focusManager.setFocused(true);
        onlineManager.setOnline(false);
        onlineManager.setOnline(true);
      });
      expect(client.bootstrapSession).toHaveBeenCalledOnce();
    } finally {
      focusManager.setFocused(undefined);
      onlineManager.setOnline(true);
    }
  });

  it("keeps the recovery view during a deferred retry and ignores repeated activation", async () => {
    let settleRetry!: (value: never) => void;
    const retry = new Promise<never>((_, reject) => {
      settleRetry = reject;
    });
    const client = {
      bootstrapSession: vi
        .fn()
        .mockRejectedValueOnce(new Error("offline"))
        .mockImplementationOnce(() => retry),
    } as unknown as ControlClient;
    const queryClient = new QueryClient();

    render(
      <MantineProvider>
        <I18nextProvider i18n={createUiI18n("en")}>
          <QueryClientProvider client={queryClient}>
            <ControlProvider client={client}>
              <main tabIndex={-1}>ready</main>
            </ControlProvider>
          </QueryClientProvider>
        </I18nextProvider>
      </MantineProvider>,
    );

    const retryButton = await screen.findByRole("button", { name: "Retry" });
    act(() => {
      fireEvent.click(retryButton);
      fireEvent.click(retryButton);
    });
    await waitFor(() =>
      expect(client.bootstrapSession).toHaveBeenCalledTimes(2),
    );
    expect(client.bootstrapSession).toHaveBeenCalledTimes(2);
    expect(
      screen.getByRole("heading", { name: "Could not load Media Finder" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Retrying request");
    settleRetry(new Error("still offline") as never);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled(),
    );
    expect(client.bootstrapSession).toHaveBeenCalledTimes(2);
  });

  it("preserves the requested route and adopts returned session language after recovery", async () => {
    let settleBootstrap!: (value: typeof session) => void;
    const secondRequest = new Promise<typeof session>((resolve) => {
      settleBootstrap = resolve;
    });
    const client = {
      bootstrapSession: vi
        .fn()
        .mockRejectedValueOnce(new Error("offline"))
        .mockImplementationOnce(() => secondRequest),
      listCollections: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
    } as unknown as ControlClient;
    const queryClient = new QueryClient();
    const router = createMemoryRouter(appRoutes, {
      initialEntries: ["/add/manual"],
    });
    const i18n = createUiI18n("ru");

    render(
      <MantineProvider>
        <I18nextProvider i18n={i18n}>
          <QueryClientProvider client={queryClient}>
            <ControlProvider client={client}>
              <RouterProvider router={router} />
            </ControlProvider>
          </QueryClientProvider>
        </I18nextProvider>
      </MantineProvider>,
    );

    await screen.findByRole("button", {
      name: "\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c",
    });
    await userEvent.setup().click(
      screen.getByRole("button", {
        name: "\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c",
      }),
    );
    settleBootstrap({ ...session, ui_locale: "en" });
    expect(
      await screen.findByRole("heading", { name: "Manual metadata" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/add/manual");
    expect(document.documentElement.lang).toBe("en");
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });
});
