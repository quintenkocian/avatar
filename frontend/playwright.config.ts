import { defineConfig, devices } from "@playwright/test";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));

// Load owner-specific secrets from the repo-root .env so the admin specs can log
// in without hardcoding the password. Only the keys the E2E suite needs are
// lifted into process.env; nothing secret is written to disk or committed.
function loadEnv(): void {
  try {
    const envPath = resolve(HERE, "..", ".env");
    const raw = readFileSync(envPath, "utf-8");
    for (const line of raw.split(/\r?\n/)) {
      const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
      if (!m) continue;
      const [, key, value] = m;
      if (!(key in process.env)) process.env[key] = value;
    }
  } catch {
    // If .env is absent the admin specs will skip; visitor specs still run.
  }
}
loadEnv();

const BASE_URL = process.env.E2E_BASE_URL || "http://127.0.0.1:8000";

export default defineConfig({
  testDir: "./e2e",
  // Serial: deterministic screenshots and no Supabase write contention.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  outputDir: "../test/screenshots/_artifacts",
  use: {
    baseURL: BASE_URL,
    actionTimeout: 15_000,
    trace: "off",
    screenshot: "off",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 } },
    },
    {
      name: "mobile",
      use: { ...devices["Pixel 5"] },
    },
  ],
});
