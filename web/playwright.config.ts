import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  webServer: { command: "npm run build && npm run preview", port: 4173, reuseExistingServer: true, timeout: 180_000 },
  use: { baseURL: "http://localhost:4173" },
});
