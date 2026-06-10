// Shared E2E helpers.
//
// Each test mints a fresh conversation UUID and records it to a tracking file;
// the Python teardown (test/cleanup_e2e.py) deletes exactly those ids from
// Supabase. Running with workers:1 (see playwright.config.ts) means the append
// is race-free.

import type { BrowserContext, Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/** Owner name as configured for this deployment (from .env via the config). */
export const OWNER_NAME = process.env.OWNER_NAME || "Quinten Kocian";
export const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || "";

const BASE = process.env.E2E_BASE_URL || "http://127.0.0.1:8000";

const HERE = dirname(fileURLToPath(import.meta.url));
const SCREENSHOT_DIR = resolve(HERE, "..", "..", "test", "screenshots");
const TRACK_FILE = resolve(SCREENSHOT_DIR, ".e2e-conversations.txt");

function ensureDir(): void {
  try {
    mkdirSync(SCREENSHOT_DIR, { recursive: true });
  } catch {
    /* already exists */
  }
}

/** Mint a fresh conversation id and record it for cleanup. */
export function newConversationId(): string {
  ensureDir();
  const id = randomUUID();
  try {
    appendFileSync(TRACK_FILE, id + "\n", "utf-8");
  } catch {
    /* tracking is best-effort; cleanup also sweeps the e2e window */
  }
  return id;
}

/** Pre-set the conversation cookie so the visitor page adopts a known id. */
export async function seedConversationCookie(
  context: BrowserContext,
  conversationId: string
): Promise<void> {
  const url = new URL(BASE);
  await context.addCookies([
    {
      name: "avatar_conversation",
      value: conversationId,
      domain: url.hostname,
      path: "/",
      sameSite: "Lax",
    },
  ]);
}

/** Set the persisted theme before the app boots (avoids the pre-paint flash). */
export async function seedTheme(page: Page, theme: "dark" | "light"): Promise<void> {
  await page.addInitScript((t) => {
    try {
      window.localStorage.setItem("avatar-theme", t as string);
    } catch {
      /* ignore */
    }
  }, theme);
}

/** Screenshot path under test/screenshots, namespaced by project (desktop/mobile). */
export function shot(name: string): string {
  return resolve(SCREENSHOT_DIR, `${name}.png`);
}

/** Log into the admin dashboard and wait for it to be visible. */
export async function adminLogin(page: Page, password: string): Promise<void> {
  await page.goto("/admin");
  await page.locator("#loginGate").waitFor({ state: "visible" });
  await page.locator("#passwordInput").fill(password);
  await page.locator("#loginBtn").click();
  await page.locator("#dashboard").waitFor({ state: "visible" });
}
