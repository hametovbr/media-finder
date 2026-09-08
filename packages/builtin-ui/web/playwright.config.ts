import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

export default defineConfig({
  testDir: "./e2e",
  outputDir: fileURLToPath(
    new URL("./browser-evidence/results", import.meta.url),
  ),
  reporter: [
    ["list"],
    [
      "html",
      {
        outputFolder: fileURLToPath(
          new URL("./browser-evidence/report", import.meta.url),
        ),
        open: "never",
      },
    ],
  ],
  use: {
    baseURL: "http://127.0.0.1:4173",
    trace: "off",
    video: "off",
  },
  webServer: {
    command:
      "pnpm exec vite --config web/vite.config.ts --host 127.0.0.1 --port 4173",
    cwd: new URL("..", import.meta.url).pathname,
    port: 4173,
    reuseExistingServer: false,
  },
});
