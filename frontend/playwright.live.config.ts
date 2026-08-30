import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["live-invitation.spec.ts", "live-demo-role.live.ts", "live-workspace-cleanup.live.ts"],
  timeout: 120_000,
  workers: 1,
  use: { baseURL: process.env.ATLAS_LIVE_URL || "http://localhost:3000", ignoreHTTPSErrors: true, trace: "retain-on-failure" },
  projects: [{ name: "incognito-chromium", use: { ...devices["Desktop Chrome"] } }],
});
