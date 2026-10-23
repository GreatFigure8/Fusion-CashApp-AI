import { defineConfig } from "@playwright/test";

const port = Number(process.env.PLAYWRIGHT_PORT ?? 3100);
const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL;

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: externalBaseUrl ?? `http://localhost:${port}`,
  },
  ...(externalBaseUrl
    ? {}
    : {
        webServer: {
          command: `npm run build && npm run start -- --port ${port}`,
          url: `http://localhost:${port}`,
          reuseExistingServer: process.env.PLAYWRIGHT_REUSE === "1",
          timeout: 300_000,
        },
      }),
});
