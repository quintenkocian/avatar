import { test, expect } from "@playwright/test";
import type { Browser } from "@playwright/test";
import {
  ADMIN_PASSWORD,
  OWNER_NAME,
  adminLogin,
  newConversationId,
  seedConversationCookie,
  shot,
} from "./fixtures";

// The headline success criterion: a three-way conversation between the visitor,
// the Avatar, and the human (owner) — plus multiple visitors with independent
// conversation_ids. Desktop only (uses several browser contexts).

test.describe("Three-way conversation", () => {
  test.skip(!ADMIN_PASSWORD, "ADMIN_PASSWORD not available from .env");

  test("visitor sees the human's live reply via polling", async ({ browser }, info) => {
    test.skip(info.project.name !== "desktop", "desktop-only multi-context flow");

    const cid = newConversationId();
    const name = `E2E Live ${cid.slice(0, 8)}`;

    // --- Visitor opens the chat and asks an instant question (visitor+avatar). ---
    const visitorCtx = await browser.newContext();
    await seedConversationCookie(visitorCtx, cid);
    const visitor = await visitorCtx.newPage();
    await visitor.goto("/");
    await visitor.locator("#nameInput").fill(name);
    await visitor.locator("#composerInput").fill("Q1");
    await visitor.locator("#sendBtn").click();
    await expect(visitor.locator(".msg--avatar .instant-tag").last()).toBeVisible();

    // --- Owner opens the same thread in admin and posts a live reply. ---
    const adminCtx = await browser.newContext();
    const admin = await adminCtx.newPage();
    await adminLogin(admin, ADMIN_PASSWORD);
    await admin.locator("#searchInput").fill(name);
    await admin.locator(`.convo-item[data-id="${cid}"]`).click();
    await expect(admin.locator("#threadView")).toBeVisible();
    const liveReply = "Hi! It's the real me jumping in to say hello.";
    await admin.locator("#adminComposerInput").fill(liveReply);
    await admin.locator("#adminComposerInput").press("Enter");
    await expect(admin.locator("#threadInner .msg--human").last()).toContainText(liveReply);

    // --- Back on the visitor page, the human bubble arrives via the poll. ---
    const humanBubble = visitor.locator(".msg--human").last();
    await expect(humanBubble).toBeVisible({ timeout: 25_000 });
    await expect(humanBubble.locator(".bubble")).toContainText(liveReply);
    // Per SPEC Q&A #4/#11: the human bubble is labelled "{owner} · live".
    await expect(humanBubble.locator(".human-tag")).toContainText(`${OWNER_NAME} · live`);

    await visitor.screenshot({ path: shot(`threeway-visitor-${info.project.name}`), fullPage: true });
    await admin.screenshot({ path: shot(`threeway-admin-${info.project.name}`), fullPage: true });

    await visitorCtx.close();
    await adminCtx.close();
  });

  test("two visitors keep independent threads; admin sees both", async ({ browser }, info) => {
    test.skip(info.project.name !== "desktop", "desktop-only multi-context flow");

    const a = await seedVisitor(browser, "Alice");
    const b = await seedVisitor(browser, "Bob");

    // Each visitor sees only their own message, never the other's.
    await expect(a.page.locator(".msg--visitor")).toContainText("Q1");
    await expect(b.page.locator(".msg--visitor")).toContainText("Q1");
    await expect(a.page.locator(".thread-messages")).not.toContainText(b.name);
    await expect(b.page.locator(".thread-messages")).not.toContainText(a.name);

    // Admin inbox shows both distinct conversations.
    const adminCtx = await browser.newContext();
    const admin = await adminCtx.newPage();
    await adminLogin(admin, ADMIN_PASSWORD);
    await expect(admin.locator(`.convo-item[data-id="${a.cid}"]`)).toBeVisible();
    await expect(admin.locator(`.convo-item[data-id="${b.cid}"]`)).toBeVisible();

    await a.ctx.close();
    await b.ctx.close();
    await adminCtx.close();
  });
});

async function seedVisitor(browser: Browser, label: string) {
  const cid = newConversationId();
  const name = `E2E ${label} ${cid.slice(0, 6)}`;
  const ctx = await browser.newContext();
  await seedConversationCookie(ctx, cid);
  const page = await ctx.newPage();
  await page.goto("/");
  await page.locator("#nameInput").fill(name);
  await page.locator("#composerInput").fill("Q1");
  await page.locator("#sendBtn").click();
  await expect(page.locator(".msg--avatar").last()).toBeVisible();
  return { ctx, page, cid, name };
}
