import "@mantine/core/styles.css";

import { Center, Loader, MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { I18nextProvider } from "react-i18next";
import { createBrowserRouter, RouterProvider } from "react-router";

import { createControlClient } from "./api/control-client";
import { ControlProvider } from "./api/control-provider";
import { appRoutes } from "./app-router";
import { createUiI18n } from "./i18n";

const queryClient = new QueryClient();
const controlClient = createControlClient();
const i18n = createUiI18n();
const router = createBrowserRouter(appRoutes);
const root = document.getElementById("root");

if (root === null) {
  throw new Error("Media Finder root element is missing");
}

async function startApplication(rootElement: HTMLElement) {
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK_API === "true") {
    const { mockWorker } = await import("./mocks/browser");
    await mockWorker.start({ onUnhandledRequest: "error" });
  }

  createRoot(rootElement).render(
    <StrictMode>
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <MantineProvider>
            <ControlProvider
              client={controlClient}
              loadingFallback={
                <Center mih="100vh">
                  <Loader aria-label={i18n.t("session.loading")} />
                </Center>
              }
            >
              <RouterProvider router={router} />
            </ControlProvider>
          </MantineProvider>
        </QueryClientProvider>
      </I18nextProvider>
    </StrictMode>,
  );
}

void startApplication(root);
