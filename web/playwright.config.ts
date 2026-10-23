import { defineConfig } from "@playwright/test";

// Expects the API on :8000 and the web app on WEB_URL (default :3210); `make e2e` starts both.
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  use: { baseURL: process.env.WEB_URL ?? "http://localhost:3210" },
});
