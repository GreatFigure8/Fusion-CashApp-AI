import { defineConfig } from "@playwright/test";

const port = Number(process.env.PLAYWRIGHT_PORT ?? 3100);
const externalBaseUrl = process.env.PLAYWRIGHT_BASE_URL;

const mockApiPort = process.env.MOCK_API_PORT ?? "3199";

export default defineConfig({
  testDir: "./e2e",
  // s19: a programmable HTTP and SSE mock of the Python API (the Next server calls it server-side).
  globalSetup: "./e2e/global-setup.ts",
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
          env: { API_BASE_URL: `http://127.0.0.1:${mockApiPort}` },
          timeout: 300_000,
        },
      }),
});
