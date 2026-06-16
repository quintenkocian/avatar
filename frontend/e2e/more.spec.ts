import { test, expect } from "@playwright/test";
import {
  ADMIN_PASSWORD,
  adminLogin,
  newConversationId,
  seedConversationCookie,
  shot,
} from "./fixtures";

// Coverage for the MORE evolution: the 4-tab admin nav, the archive/restore
// flow, the additional-instructions editor, the Supabase-backed FAQ editor, and
// the visitor ?m= deep link. These mirror the manually-validated flows.
//
// NOTE: this environment (ubuntu26.04-arm64) has no Playwright browser build, so
// the suite was exercised via Windows Chromium for screenshots; these specs make
// the same flows reproducible wherever a Playwright browser is available.

test.describe("MORE — admin tabs", () => {
  test.skip(!ADMIN_PASSWORD, "ADMIN_PASSWORD not available from .env");

  test("the main nav switches between the four sections", async ({ page }, info) => {
    await adminLogin(page, ADMIN_PASSWORD);
    const tabs = ["conversations", "archive", "instructions", "faq"] as const;
    const panels = {
      conversations: "#panel-conversations",
      archive: "#panel-archive",
      instructions: "#panel-instructions",
      faq: "#panel-faq",
    };
    for (const tab of tabs) {
      await page.locator(`.admin-tab[data-tab="${tab}"]`).click();
      await expect(page.locator(panels[tab])).toBeVisible();
      await expect(page.locator(`.admin-tab[data-tab="${tab}"]`)).toHaveClass(/is-on/);
    }
    await page.screenshot({ path: shot(`more-faq-${info.project.name}`), fullPage: true });
  });

  test("archive then restore a whole conversation", async ({ page, request }) => {
    // Seed a live conversation via the public instant endpoint.
    const cid = newConversationId();
    const name = `E2E-ARC ${cid.slice(0, 8)}`;
    const res = await request.post("/api/instant", {
      data: { conversation_id: cid, name, message: "Q1" },
    });
    expect(res.ok()).toBeTruthy();

    await adminLogin(page, ADMIN_PASSWORD);

    // Open it in the Conversations tab and archive it (auto-accept the confirm).
    await page.locator("#searchInput").fill(name);
    await page.locator(`.convo-item[data-id="${cid}"]`).click();
    await expect(page.locator("#threadView")).toBeVisible();
    page.once("dialog", (d) => d.accept());
    await page.locator("#archiveBtn").click();

    // It now appears under the Archive tab.
    await page.locator('.admin-tab[data-tab="archive"]').click();
    const archiveRow = page.locator(`#archiveList .convo-item[data-id="${cid}"]`);
    await expect(archiveRow).toBeVisible();

    // Open it (read-only) and restore it back to the live inbox.
    await archiveRow.click();
    await expect(page.locator("#archiveThreadView")).toBeVisible();
    await page.locator("#archiveRestoreBtn").click();
    await expect(archiveRow).toBeHidden();

    // Back under Conversations it is live again (cleanup deletes it afterwards).
    await page.locator('.admin-tab[data-tab="conversations"]').click();
    await page.locator("#searchInput").fill(name);
    await expect(page.locator(`.convo-item[data-id="${cid}"]`)).toBeVisible();
  });

  test("additional instructions save round-trips", async ({ page }) => {
    await adminLogin(page, ADMIN_PASSWORD);
    await page.locator('.admin-tab[data-tab="instructions"]').click();
    const ta = page.locator("#instructionsTextarea");
    const original = await ta.inputValue();
    const marker = `E2E instruction ${Date.now()}`;
    try {
      await ta.fill(marker);
      await page.locator("#instructionsSaveBtn").click();
      await expect(page.locator("#instructionsStatus")).toContainText(/saved/i);
      // Reload the tab and confirm persistence.
      await page.locator('.admin-tab[data-tab="conversations"]').click();
      await page.reload();
      await page.locator('.admin-tab[data-tab="instructions"]').click();
      await expect(page.locator("#instructionsTextarea")).toHaveValue(marker);
    } finally {
      // Restore the original instructions so the live prompt is unchanged.
      await page.locator("#instructionsTextarea").fill(original);
      await page.locator("#instructionsSaveBtn").click();
      await expect(page.locator("#instructionsStatus")).toContainText(/saved/i);
    }
  });

  test("FAQ editor creates, edits and deletes a row", async ({ page }) => {
    await adminLogin(page, ADMIN_PASSWORD);
    await page.locator('.admin-tab[data-tab="faq"]').click();
    await expect(page.locator(".faq-row[data-id]").first()).toBeVisible();

    // Add a new row.
    await page.locator("#faqAddBtn").click();
    const newRow = page.locator(".faq-row.is-new").first();
    await newRow.locator(".faq-concise").fill("e2e routing phrase");
    await newRow.locator(".faq-question").fill("E2E throwaway question?");
    await newRow.locator(".faq-answer").fill("E2E throwaway answer.");
    await newRow.locator(".faq-save").click();
    // Once saved it gains a data-id (no longer .is-new).
    await expect(newRow).not.toHaveClass(/is-new/);
    const savedId = await newRow.getAttribute("data-id");
    expect(savedId).toBeTruthy();

    // Delete it (auto-accept confirm) so the FAQ table returns to its seed state.
    page.once("dialog", (d) => d.accept());
    await page.locator(`.faq-row[data-id="${savedId}"] .faq-delete`).click();
    await expect(page.locator(`.faq-row[data-id="${savedId}"]`)).toHaveCount(0);
  });
});

test.describe("MORE — visitor ?m= deep link", () => {
  test("?m=text auto-submits as a visitor message", async ({ page, context }) => {
    const cid = newConversationId();
    await seedConversationCookie(context, cid);
    await page.goto("/?m=" + encodeURIComponent("Tell me about your background."));
    // The optimistic visitor bubble appears, and the URL param is stripped.
    await expect(page.locator(".msg--visitor .bubble").first()).toContainText(
      /background/i
    );
    await expect(page).toHaveURL(/\/$|\/(?!\?m=)/);
    // An avatar reply streams in (cleanup deletes this conversation afterwards).
    await expect(page.locator(".msg--avatar .bubble").first()).toBeVisible({
      timeout: 30_000,
    });
  });
});
