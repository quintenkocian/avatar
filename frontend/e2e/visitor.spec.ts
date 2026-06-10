import { test, expect } from "@playwright/test";
import {
  OWNER_NAME,
  newConversationId,
  seedConversationCookie,
  seedTheme,
  shot,
} from "./fixtures";

// The visitor chat experience: intro, instant Qn, streaming chat, deep link,
// keep-chat persistence, reset, and rate-limit handling. Dark + light, desktop +
// mobile (the project name namespaces every screenshot).

test.describe("Visitor chat", () => {
  test("intro screen renders, dark theme", async ({ page, context }, info) => {
    await seedTheme(page, "dark");
    await seedConversationCookie(context, newConversationId());
    await page.goto("/");

    // Owner name is personalized from /api/config, never hardcoded.
    await expect(page.locator("#brandSub")).toContainText(OWNER_NAME);
    await expect(page.locator("#introHeading")).toContainText("digital twin");
    await expect(page.locator("#suggestRow .chip")).toHaveCount(3);
    // Composer takes focus on load (hard requirement).
    await expect(page.locator("#composerInput")).toBeFocused();
    await expect(page).toHaveTitle(new RegExp(OWNER_NAME));

    await page.screenshot({ path: shot(`visitor-intro-dark-${info.project.name}`), fullPage: true });
  });

  test("intro screen renders, light theme", async ({ page, context }, info) => {
    await seedTheme(page, "light");
    await seedConversationCookie(context, newConversationId());
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await expect(page.locator("#introHeading")).toContainText("digital twin");
    await page.screenshot({ path: shot(`visitor-intro-light-${info.project.name}`), fullPage: true });
  });

  test("theme toggle flips dark <-> light and persists", async ({ page, context }) => {
    await seedTheme(page, "dark");
    await seedConversationCookie(context, newConversationId());
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    await page.locator("#themeToggle").first().click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    const stored = await page.evaluate(() => localStorage.getItem("avatar-theme"));
    expect(stored).toBe("light");
  });

  test("instant Qn answer with no LLM call", async ({ page, context }, info) => {
    await seedConversationCookie(context, newConversationId());
    await page.goto("/");
    await page.locator("#composerInput").fill("Q1");
    await page.locator("#sendBtn").click();

    // A visitor bubble (the "Q1") and an avatar bubble carrying the instant tag.
    const avatar = page.locator(".msg--avatar").last();
    await expect(avatar.locator(".instant-tag")).toHaveText(/instant · Q1/);
    await expect(avatar.locator(".bubble")).toContainText("Q1:");
    // Composer regains focus after sending.
    await expect(page.locator("#composerInput")).toBeFocused();
    await page.screenshot({ path: shot(`visitor-qn-${info.project.name}`), fullPage: true });
  });

  test("streaming chat returns a grounded answer", async ({ page, context }, info) => {
    await seedConversationCookie(context, newConversationId());
    await page.goto("/");
    await page.locator("#composerInput").fill("In one sentence, where are you from?");
    await page.locator("#composerInput").press("Enter");

    const bubble = page.locator(".msg--avatar .bubble").last();
    await expect(bubble).not.toBeEmpty({ timeout: 30_000 });
    // The intro hero is hidden once the thread has content.
    await expect(page.locator("#intro")).toBeHidden();
    await page.screenshot({ path: shot(`visitor-chat-${info.project.name}`), fullPage: true });
  });

  test("suggestion chip submits immediately", async ({ page, context }) => {
    await seedConversationCookie(context, newConversationId());
    await page.goto("/");
    await page.locator('#suggestRow .chip', { hasText: "background" }).click();
    // An optimistic visitor bubble appears immediately.
    await expect(page.locator(".msg--visitor").last()).toContainText("background");
  });

  test("deep link ?q=1 answers on arrival and clears the param", async ({ page, context }, info) => {
    await seedConversationCookie(context, newConversationId());
    await page.goto("/?q=1");
    const avatar = page.locator(".msg--avatar").last();
    await expect(avatar.locator(".instant-tag")).toHaveText(/instant · Q1/, { timeout: 20_000 });
    // The ?q= param is stripped from the URL.
    await expect.poll(() => new URL(page.url()).searchParams.get("q")).toBeNull();
    await page.screenshot({ path: shot(`visitor-deeplink-${info.project.name}`), fullPage: true });
  });

  test("keep-chat restores the thread on reload", async ({ page, context }) => {
    const cid = newConversationId();
    await seedConversationCookie(context, cid);
    await page.goto("/");
    await page.locator("#composerInput").fill("Q1");
    await page.locator("#sendBtn").click();
    await expect(page.locator(".msg--avatar .instant-tag").last()).toBeVisible();

    // Reload: the persisted thread should be restored from Supabase.
    await page.reload();
    await expect(page.locator(".msg--avatar .bubble").last()).toContainText("Q1:");
    await expect(page.locator(".msg--visitor").last()).toBeVisible();
  });

  test("reset clears the thread and restores the intro", async ({ page, context }) => {
    await seedConversationCookie(context, newConversationId());
    await page.goto("/");
    await page.locator("#composerInput").fill("Q1");
    await page.locator("#sendBtn").click();
    await expect(page.locator(".msg--avatar").last()).toBeVisible();

    // Click whichever reset control is visible for this viewport (desktop topbar
    // vs the mobile secondary bar).
    await page.locator("#resetBtn:visible, #resetBtnMobile:visible").first().click();
    await expect(page.locator(".msg--avatar")).toHaveCount(0);
    await expect(page.locator(".msg--visitor")).toHaveCount(0);
    await expect(page.locator("#intro")).toBeVisible();
  });

  test("rate limit (429) shows the friendly banner", async ({ page, context }) => {
    await seedConversationCookie(context, newConversationId());
    // Force the chat endpoint to 429 so we test the UI path deterministically.
    await page.route("**/api/chat", (route) =>
      route.fulfill({
        status: 429,
        contentType: "application/json",
        body: JSON.stringify({ error: "rate_limited" }),
      })
    );
    await page.goto("/");
    await page.locator("#composerInput").fill("Tell me about your work.");
    await page.locator("#sendBtn").click();
    await expect(page.locator("#composerBanner")).toBeVisible();
    await expect(page.locator("#composerBanner")).toContainText(/too quickly/i);
  });
});
