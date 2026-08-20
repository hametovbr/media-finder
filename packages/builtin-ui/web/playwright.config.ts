import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:4173",
  },
  webServer: {
    command:
      "pnpm exec vite --config web/vite.config.ts --host 127.0.0.1 --port 4173",
    cwd: new URL("..", import.meta.url).pathname,
    port: 4173,
    reuseExistingServer: false,
  },
});
