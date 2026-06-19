import { test as setup } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { ADMIN_PASSWORD, ADMIN_STORAGE, adminLogin } from "./fixtures";

// One-time admin login. Saves the authenticated storage state to ADMIN_STORAGE
// so the admin specs reuse a single session (via test.use({ storageState }))
// instead of logging in per test — which would trip the production 5/min admin
// login rate-limit. This runs as a dependency of the desktop/mobile projects
// (see playwright.config.ts) and, because the default testMatch only picks up
// *.spec.ts, this *.setup.ts is run by the setup project alone.
setup("authenticate admin", async ({ page }) => {
  mkdirSync(dirname(ADMIN_STORAGE), { recursive: true });
  if (!ADMIN_PASSWORD) {
    // No secret available (e.g. CI without .env): write an empty state so the
    // dependent specs can still load a storageState path before they skip.
    await page.context().storageState({ path: ADMIN_STORAGE });
    setup.skip(true, "ADMIN_PASSWORD not available from .env");
    return;
  }
  await adminLogin(page, ADMIN_PASSWORD);
  await page.context().storageState({ path: ADMIN_STORAGE });
});
