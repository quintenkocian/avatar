// Small shared utilities for both the visitor and admin screens.
// Pure functions only — no DOM side effects beyond cookie access.

/**
 * Derive up-to-two-character initials from a free-text name.
 * "Jordan M." -> "JM", "priya" -> "PR", "" -> "?".
 * Falls back to the first two letters of a single token, then "?".
 */
export function initials(name: string | null | undefined): string {
  const raw = (name ?? "").trim();
  if (!raw) return "?";
  const words = raw.split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) {
    const w = words[0].replace(/[^\p{L}\p{N}]/gu, "");
    if (!w) return "?";
    return w.slice(0, 2).toUpperCase();
  }
  const first = words[0].replace(/[^\p{L}\p{N}]/gu, "");
  const last = words[words.length - 1].replace(/[^\p{L}\p{N}]/gu, "");
  const a = first.charAt(0);
  const b = last.charAt(0);
  const out = (a + b).toUpperCase();
  return out || "?";
}

/**
 * Format an ISO timestamp (or Date) as a short, locale-aware clock time,
 * e.g. "2:41 PM". Invalid input returns an empty string.
 */
export function formatTime(value: string | number | Date): string {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
  });
}

/**
 * Longer, contextual timestamp for thread headers / day separators,
 * e.g. "Today · 2:41 PM" or "Mon · 2:41 PM" or "Jan 4 · 2:41 PM".
 */
export function formatDayTime(value: string | number | Date): string {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const time = formatTime(d);
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) return `Today · ${time}`;

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday =
    d.getFullYear() === yesterday.getFullYear() &&
    d.getMonth() === yesterday.getMonth() &&
    d.getDate() === yesterday.getDate();
  if (isYesterday) return `Yesterday · ${time}`;

  const withinWeek = (now.getTime() - d.getTime()) / 86_400_000 < 7;
  if (withinWeek) {
    const day = d.toLocaleDateString(undefined, { weekday: "short" });
    return `${day} · ${time}`;
  }
  const date = d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return `${date} · ${time}`;
}

/**
 * Compact, inbox-style relative timestamp: "2:45", "Yest", "Mon", "Jan 4".
 */
export function formatInboxTime(value: string | number | Date): string {
  const d = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) {
    return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (
    d.getFullYear() === yesterday.getFullYear() &&
    d.getMonth() === yesterday.getMonth() &&
    d.getDate() === yesterday.getDate()
  ) {
    return "Yest";
  }
  const withinWeek = (now.getTime() - d.getTime()) / 86_400_000 < 7;
  if (withinWeek) {
    return d.toLocaleDateString(undefined, { weekday: "short" });
  }
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

/**
 * Escape a string for safe insertion as HTML text/attribute content.
 * Always use before building markup from untrusted strings.
 */
export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/**
 * Generate an RFC-4122 v4 UUID. Uses the platform crypto.randomUUID where
 * available, with a crypto.getRandomValues fallback for older engines.
 */
export function uuid(): string {
  const c = globalThis.crypto;
  if (c && typeof c.randomUUID === "function") {
    return c.randomUUID();
  }
  const bytes = new Uint8Array(16);
  c.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10
  const hex: string[] = [];
  for (let i = 0; i < 256; i++) hex.push((i + 0x100).toString(16).slice(1));
  const b = bytes;
  return (
    hex[b[0]] + hex[b[1]] + hex[b[2]] + hex[b[3]] + "-" +
    hex[b[4]] + hex[b[5]] + "-" +
    hex[b[6]] + hex[b[7]] + "-" +
    hex[b[8]] + hex[b[9]] + "-" +
    hex[b[10]] + hex[b[11]] + hex[b[12]] + hex[b[13]] + hex[b[14]] + hex[b[15]]
  );
}

// --- Cookie helpers -------------------------------------------------------

/** Read a cookie value by name, or null if absent. */
export function getCookie(name: string): string | null {
  const target = encodeURIComponent(name) + "=";
  const parts = document.cookie ? document.cookie.split("; ") : [];
  for (const part of parts) {
    if (part.startsWith(target)) {
      return decodeURIComponent(part.slice(target.length));
    }
  }
  return null;
}

/**
 * Set a first-party cookie. Defaults: ~1 year, path=/, SameSite=Lax.
 * (The visitor "Keep chat" cookie relies on these defaults — see SPEC.)
 */
export function setCookie(
  name: string,
  value: string,
  opts: { days?: number; path?: string; sameSite?: "Lax" | "Strict" | "None" } = {}
): void {
  const days = opts.days ?? 365;
  const path = opts.path ?? "/";
  const sameSite = opts.sameSite ?? "Lax";
  const maxAge = Math.floor(days * 86_400);
  let cookie =
    encodeURIComponent(name) +
    "=" +
    encodeURIComponent(value) +
    `; path=${path}; max-age=${maxAge}; SameSite=${sameSite}`;
  // A SameSite=None cookie must also be Secure to be accepted by browsers.
  if (sameSite === "None" || location.protocol === "https:") {
    cookie += "; Secure";
  }
  document.cookie = cookie;
}

/** Delete a cookie by name (path must match the one used to set it). */
export function deleteCookie(name: string, path = "/"): void {
  document.cookie =
    encodeURIComponent(name) + `=; path=${path}; max-age=0; SameSite=Lax`;
}

/**
 * Scroll an element to its bottom. Used to keep conversations pinned to the
 * latest message. `smooth` animates; otherwise it jumps (used on initial load).
 */
export function scrollToBottom(el: HTMLElement, smooth = false): void {
  el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
}
