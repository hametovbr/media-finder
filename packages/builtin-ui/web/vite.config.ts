import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig(({ command }) => ({
  root: import.meta.dirname,
  plugins: [react()],
  publicDir: command === "serve" ? "public" : false,
  build: {
    emptyOutDir: true,
    outDir: "../src/media_finder_builtin_ui/static",
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    exclude: ["e2e/**"],
    setupFiles: ["./src/test/setup.ts"],
  },
}));
