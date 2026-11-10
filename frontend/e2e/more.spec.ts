import { test, expect } from "@playwright/test";
import {
  ADMIN_PASSWORD,
  ADMIN_STORAGE,
  newConversationId,
  openAdmin,
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
  // Reuse the saved admin session (auth.setup.ts) instead of logging in per
  // test, so this group stays under the production 5/min login rate-limit.
  test.use({ storageState: ADMIN_STORAGE });

  test("the main nav switches between the four sections", async ({ page }, info) => {
    await openAdmin(page);
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

  test("archive then restore a whole conversation", async ({ page, request }, info) => {
    // Archive/restore is viewport-independent logic (same DOM + handlers as
    // desktop, which covers it); the mobile master/detail layout is covered by
    // the admin "mobile master/detail" test. On mobile this flow only adds a
    // flaky pointer hit-test against the appbar, so keep it desktop-only.
    test.skip(info.project.name !== "desktop", "viewport-independent; mobile layout covered by admin master/detail");
    // Seed a live conversation via the public instant endpoint.
    const cid = newConversationId();
    const name = `E2E-ARC ${cid.slice(0, 8)}`;
    const res = await request.post("/api/instant", {
      data: { conversation_id: cid, name, message: "Q1" },
    });
    expect(res.ok()).toBeTruthy();

    await openAdmin(page);

    // Open it in the Conversations tab and archive it (auto-accept the confirm).
    await page.locator("#searchInput").fill(name);
    await page.locator(`.convo-item[data-id="${cid}"]`).click();
    await expect(page.locator("#threadView")).toBeVisible();
    page.once("dialog", (d) => d.accept());
    await page.locator("#archiveBtn").click();
    // Wait for the archive write to commit: the handler removes the row from the
    // inbox only after the POST resolves. Switching tabs before this races the
    // archive-list load against the still-in-flight write.
    await expect(page.locator(`.convo-item[data-id="${cid}"]`)).toBeHidden();

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
    await openAdmin(page);
    // Open the Instructions tab and wait for its lazy GET to land before editing.
    // loadInstructions() fires asynchronously on tab-open and writes the fetched
    // value into the textarea; if we fill before it resolves, the late response
    // clobbers our marker and the save persists the wrong value.
    await Promise.all([
      page.waitForResponse(
        (r) =>
          new URL(r.url()).pathname === "/admin/instructions" &&
          r.request().method() === "GET"
      ),
      page.locator('.admin-tab[data-tab="instructions"]').click(),
    ]);
    const ta = page.locator("#instructionsTextarea");
    const original = await ta.inputValue();
    const marker = `E2E instruction ${Date.now()}`;
    try {
      await ta.fill(marker);
      await page.locator("#instructionsSaveBtn").click();
      await expect(page.locator("#instructionsStatus")).toContainText(/saved/i);
      // Reload and confirm persistence. Wait for the dashboard to re-initialise
      // after reload before clicking the tab — instructions load lazily on first
      // tab-open, and a click landing before the SPA wires its handlers (flaky on
      // the slower mobile profile) would never trigger the load.
      await page.locator('.admin-tab[data-tab="conversations"]').click();
      await page.reload();
      await expect(page.locator("#dashboard")).toBeVisible();
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
    await openAdmin(page);
    await page.locator('.admin-tab[data-tab="faq"]').click();
    await expect(page.locator(".faq-row[data-id]").first()).toBeVisible();

    // Add a new row. It is prepended, so it's the first .faq-row — a stable
    // handle (selecting by .is-new would stop matching the moment it's saved).
    await page.locator("#faqAddBtn").click();
    const newRow = page.locator(".faq-row").first();
    await expect(newRow).toHaveClass(/is-new/);
    await newRow.locator(".faq-concise").fill("e2e routing phrase");
    await newRow.locator(".faq-question").fill("E2E throwaway question?");
    await newRow.locator(".faq-answer").fill("E2E throwaway answer.");
    await newRow.locator(".faq-save").click();
    // Once saved the same row gains a data-id and loses is-new.
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
