// @ts-check
import { defineConfig, devices } from "@playwright/test";

// E2E runs against the docker-compose stack (web on :8080 -> api on :8000),
// or `npm run dev` + uvicorn locally with E2E_BASE_URL=http://localhost:5173.
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:8080",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
