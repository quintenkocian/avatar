import { test, expect } from "@playwright/test";
import {
  ADMIN_PASSWORD,
  OWNER_NAME,
  adminLogin,
  newConversationId,
  seedTheme,
  shot,
} from "./fixtures";

// The admin dashboard: auth gate, inbox, thread open (mark read), composing a
// human message, logout, and the mobile master/detail flow.

test.describe("Admin dashboard", () => {
  test.skip(!ADMIN_PASSWORD, "ADMIN_PASSWORD not available from .env");

  test("login gate renders (dark + light)", async ({ page }, info) => {
    // The login gate has no theme toggle (only the dashboard does); it renders in
    // the persisted theme, so we capture each by seeding localStorage + reload.
    await seedTheme(page, "dark");
    await page.goto("/admin");
    await expect(page.locator("#loginGate")).toBeVisible();
    await expect(page.locator("#dashboard")).toBeHidden();
    await expect(page.locator("#passwordInput")).toBeFocused();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.screenshot({ path: shot(`admin-login-dark-${info.project.name}`), fullPage: true });

    // Add a light seed (init scripts run in order, so this one wins) and reload.
    await seedTheme(page, "light");
    await page.reload();
    await expect(page.locator("#loginGate")).toBeVisible();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.screenshot({ path: shot(`admin-login-light-${info.project.name}`), fullPage: true });
  });

  test("wrong password shows an error and stays gated", async ({ page }) => {
    await page.goto("/admin");
    await page.locator("#passwordInput").fill("definitely-not-the-password");
    await page.locator("#loginBtn").click();
    await expect(page.locator("#loginError")).toBeVisible();
    await expect(page.locator("#loginError")).toContainText(/not correct/i);
    await expect(page.locator("#dashboard")).toBeHidden();
  });

  test("correct password opens the dashboard", async ({ page }, info) => {
    await adminLogin(page, ADMIN_PASSWORD);
    await expect(page.locator(".appbar .brand-name")).toHaveText("Avatar");
    await expect(page.locator("#ownerLabel")).toContainText(OWNER_NAME.split(" ")[0]);
    await page.screenshot({ path: shot(`admin-dashboard-${info.project.name}`), fullPage: true });
  });

  test("inbox lists a seeded conversation and opens its thread", async ({ page, request }, info) => {
    // Seed a conversation through the public API so it appears in the inbox.
    const cid = newConversationId();
    const name = `E2E ${cid.slice(0, 8)}`;
    const res = await request.post("/api/instant", {
      data: { conversation_id: cid, name, message: "Q1" },
    });
    expect(res.ok()).toBeTruthy();

    await adminLogin(page, ADMIN_PASSWORD);
    // Find it via search (the inbox may hold many conversations).
    await page.locator("#searchInput").fill(name);
    const row = page.locator(`.convo-item[data-id="${cid}"]`);
    await expect(row).toBeVisible();
    await expect(row.locator(".convo-name")).toHaveText(name);

    await row.click();
    await expect(page.locator("#threadView")).toBeVisible();
    await expect(page.locator("#threadName")).toHaveText(name);
    // The seeded visitor + avatar rows render.
    await expect(page.locator("#threadInner .msg--visitor")).toHaveCount(1);
    await expect(page.locator("#threadInner .msg--avatar")).toHaveCount(1);
    await page.screenshot({ path: shot(`admin-thread-${info.project.name}`), fullPage: true });
  });

  test("owner can post a human message into a thread", async ({ page, request }, info) => {
    const cid = newConversationId();
    const name = `E2E ${cid.slice(0, 8)}`;
    await request.post("/api/instant", {
      data: { conversation_id: cid, name, message: "Q1" },
    });

    await adminLogin(page, ADMIN_PASSWORD);
    await page.locator("#searchInput").fill(name);
    await page.locator(`.convo-item[data-id="${cid}"]`).click();
    await expect(page.locator("#threadView")).toBeVisible();

    const reply = "Thanks for reaching out — this is the real me.";
    await page.locator("#adminComposerInput").fill(reply);
    // Enter sends (the documented primary action); robust across viewports.
    await page.locator("#adminComposerInput").press("Enter");

    const human = page.locator("#threadInner .msg--human").last();
    await expect(human).toBeVisible();
    await expect(human.locator(".bubble")).toContainText(reply);
    await expect(human.locator(".human-tag")).toContainText(/You · sent to visitor/);
    await page.screenshot({ path: shot(`admin-human-reply-${info.project.name}`), fullPage: true });
  });

  test("logout returns to the gate", async ({ page }) => {
    await adminLogin(page, ADMIN_PASSWORD);
    await page.locator("#logoutBtn").click();
    await expect(page.locator("#loginGate")).toBeVisible();
    await expect(page.locator("#dashboard")).toBeHidden();
  });

  test("mobile master/detail flips to the thread and back", async ({ page, request }, info) => {
    test.skip(info.project.name !== "mobile", "mobile-only flow");
    const cid = newConversationId();
    const name = `E2E ${cid.slice(0, 8)}`;
    await request.post("/api/instant", {
      data: { conversation_id: cid, name, message: "Q1" },
    });

    await adminLogin(page, ADMIN_PASSWORD);
    await page.locator("#searchInput").fill(name);
    await page.locator(`.convo-item[data-id="${cid}"]`).click();
    // Detail view is shown (dashboard gains .show-detail on mobile).
    await expect(page.locator("#dashboard")).toHaveClass(/show-detail/);
    await page.screenshot({ path: shot(`admin-mobile-detail-${info.project.name}`), fullPage: true });

    // Click whichever back control is visible at this breakpoint (the appbar
    // back button or the in-thread one); both return to the inbox.
    await page.locator("#mobileBackBtn:visible, #threadBackBtn:visible").first().click();
    await expect(page.locator("#dashboard")).not.toHaveClass(/show-detail/);
  });
});
