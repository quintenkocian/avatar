// Admin dashboard screen logic. Entry point for admin.html.
//
// Responsibilities (see docs/ARCHITECTURE.md §9 "Admin", SPEC "Human Admin
// Experience", design-system/docs/ux-flows.md §G, mockups/Admin Dashboard.html):
//   - Login gate vs dashboard, driven by adminMe()/adminLogin()/adminLogout().
//   - Inbox: list conversations (most-recent first) with read / unread /
//     needs-you / active states, client-side search + filter chips.
//   - Thread: open a conversation (clears unread + attention server-side),
//     render the three role bubbles, header (id/started/count), the
//     "Avatar asked for you" flag + "Mark resolved" button, scroll to latest.
//   - Compose: post a `human` row (the Avatar does NOT react). Enter sends,
//     Shift+Enter newline, focus on open.
//   - Keyboard: ArrowUp/ArrowDown move (and open) the selection.
//   - Polling: refresh the inbox and the open thread (~10s) so new visitor
//     activity / needs-attention surfaces without reload; de-dupe by id.
//   - Mobile master/detail: tapping a conversation flips #dashboard to
//     .show-detail; back controls return to the inbox.
//   - Theme toggle via theme.ts. No emoji, no gradients in chrome.

import {
  adminMe,
  adminLogin,
  adminLogout,
  adminListConversations,
  adminOpenConversation,
  adminPostMessage,
  adminResolve,
  getConfig,
  ApiError,
  type Conversation,
  type ConversationSummary,
  type Message,
} from "../api";
import { attachThemeToggle, initTheme } from "../theme";
import { renderMarkdown } from "../markdown";
import {
  initials,
  escapeHtml,
  formatTime,
  formatDayTime,
  formatInboxTime,
  scrollToBottom,
} from "../util";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const POLL_INTERVAL_MS = 10_000;
const MOBILE_BREAKPOINT = 860;
const HUMAN_FILE = "/avatar-human.png";
const TWIN_FILE = "/avatar-robot-round.png";

type FilterMode = "all" | "attention" | "unread";

// Tool-status icon + label mapping for the technical layer in the thread.
function toolIcon(name: string): string {
  if (name === "push_tool") return "i-mail";
  if (name === "faq_tool") return "i-check";
  return "i-tool";
}

// ---------------------------------------------------------------------------
// Element lookup helpers
// ---------------------------------------------------------------------------

function el<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Admin: missing #${id} in admin.html`);
  return node as T;
}

// ---------------------------------------------------------------------------
// Screen state
// ---------------------------------------------------------------------------

interface AdminState {
  authed: boolean;
  ownerName: string;
  summaries: ConversationSummary[];
  search: string;
  filter: FilterMode;
  activeId: string | null;
  /** Messages currently rendered in the open thread, in order. */
  threadMessages: Message[];
  /** ids of messages already rendered (de-dupe across polls/sends). */
  renderedIds: Set<number>;
  /** Highest message id seen in the open thread (for incremental poll). */
  lastSeenId: number | null;
  threadName: string | null;
  threadNeedsAttention: boolean;
  threadStartedAt: string | null;
}

const state: AdminState = {
  authed: false,
  ownerName: "the owner",
  summaries: [],
  search: "",
  filter: "all",
  activeId: null,
  threadMessages: [],
  renderedIds: new Set<number>(),
  lastSeenId: null,
  threadName: null,
  threadNeedsAttention: false,
  threadStartedAt: null,
};

let pollTimer: number | null = null;

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

const dom = {
  // Auth
  loginGate: el<HTMLElement>("loginGate"),
  loginForm: el<HTMLFormElement>("loginForm"),
  passwordInput: el<HTMLInputElement>("passwordInput"),
  loginError: el<HTMLParagraphElement>("loginError"),
  loginBtn: el<HTMLButtonElement>("loginBtn"),
  dashboard: el<HTMLElement>("dashboard"),
  logoutBtn: el<HTMLButtonElement>("logoutBtn"),
  ownerLabel: el<HTMLElement>("ownerLabel"),
  // Mobile nav
  mobileBackBtn: el<HTMLButtonElement>("mobileBackBtn"),
  threadBackBtn: el<HTMLButtonElement>("threadBackBtn"),
  // Inbox
  convoCount: el<HTMLElement>("convoCount"),
  searchInput: el<HTMLInputElement>("searchInput"),
  filterRow: el<HTMLElement>("filterRow"),
  convoList: el<HTMLElement>("convoList"),
  listEmpty: el<HTMLElement>("listEmpty"),
  // Thread
  threadEmpty: el<HTMLElement>("threadEmpty"),
  threadView: el<HTMLElement>("threadView"),
  threadInitials: el<HTMLElement>("threadInitials"),
  threadName: el<HTMLElement>("threadName"),
  threadSub: el<HTMLElement>("threadSub"),
  attnFlag: el<HTMLElement>("attnFlag"),
  resolveBtn: el<HTMLButtonElement>("resolveBtn"),
  thread: el<HTMLElement>("thread"),
  threadInner: el<HTMLElement>("threadInner"),
  adminComposerInput: el<HTMLTextAreaElement>("adminComposerInput"),
  adminSendBtn: el<HTMLButtonElement>("adminSendBtn"),
};

function init(): void {
  initTheme();
  attachThemeToggle("themeToggle");

  wireAuth();
  wireInbox();
  wireThread();
  wireGlobalKeys();

  // Owner name is decorative here ("You" already in markup); fetch it so any
  // owner-aware copy is correct and never hardcoded.
  void getConfig()
    .then((cfg) => {
      if (cfg.owner_name) {
        state.ownerName = cfg.owner_name;
        // Keep the chip label friendly; show the owner's first name.
        dom.ownerLabel.textContent = firstName(cfg.owner_name) || "You";
      }
    })
    .catch(() => {
      /* config is non-critical for admin; ignore failures */
    });

  void bootAuth();
}

function firstName(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "";
  return trimmed.split(/\s+/)[0];
}

// ---------------------------------------------------------------------------
// Auth flow
// ---------------------------------------------------------------------------

async function bootAuth(): Promise<void> {
  let authed = false;
  try {
    authed = await adminMe();
  } catch {
    authed = false;
  }
  if (authed) {
    await enterDashboard();
  } else {
    showLoginGate();
  }
}

function showLoginGate(): void {
  state.authed = false;
  stopPolling();
  dom.dashboard.hidden = true;
  dom.loginGate.hidden = false;
  dom.loginError.hidden = true;
  dom.passwordInput.value = "";
  // Defer focus until the gate is laid out.
  window.requestAnimationFrame(() => dom.passwordInput.focus());
}

async function enterDashboard(): Promise<void> {
  state.authed = true;
  dom.loginGate.hidden = true;
  dom.dashboard.hidden = false;
  await refreshInbox();
  startPolling();
  window.requestAnimationFrame(() => dom.searchInput.focus());
}

function wireAuth(): void {
  dom.loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const password = dom.passwordInput.value;
    if (!password) {
      showLoginError("Enter your admin password.");
      return;
    }
    setLoginBusy(true);
    dom.loginError.hidden = true;
    try {
      const ok = await adminLogin(password);
      if (ok) {
        dom.passwordInput.value = "";
        await enterDashboard();
      } else {
        showLoginError("That password is not correct. Try again.");
        dom.passwordInput.select();
      }
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `Sign-in failed (${err.status || "network"}). Try again.`
          : "Sign-in failed. Try again.";
      showLoginError(msg);
    } finally {
      setLoginBusy(false);
    }
  });

  dom.logoutBtn.addEventListener("click", async () => {
    stopPolling();
    try {
      await adminLogout();
    } catch {
      /* clearing locally is enough even if the request fails */
    }
    resetThreadState();
    state.summaries = [];
    dom.convoList
      .querySelectorAll(".convo-item")
      .forEach((node) => node.remove());
    showLoginGate();
  });
}

function setLoginBusy(busy: boolean): void {
  dom.loginBtn.disabled = busy;
  dom.passwordInput.disabled = busy;
}

function showLoginError(message: string): void {
  dom.loginError.textContent = message;
  dom.loginError.hidden = false;
}

// ---------------------------------------------------------------------------
// Inbox
// ---------------------------------------------------------------------------

function wireInbox(): void {
  dom.searchInput.addEventListener("input", () => {
    state.search = dom.searchInput.value.trim().toLowerCase();
    renderInbox();
  });

  dom.filterRow.addEventListener("click", (event) => {
    const chip = (event.target as HTMLElement).closest<HTMLElement>(
      ".filter-chip"
    );
    if (!chip) return;
    const filter = (chip.dataset.filter ?? "all") as FilterMode;
    state.filter = filter;
    dom.filterRow.querySelectorAll(".filter-chip").forEach((c) => {
      c.classList.toggle("is-on", c === chip);
    });
    renderInbox();
  });

  dom.convoList.addEventListener("click", (event) => {
    const item = (event.target as HTMLElement).closest<HTMLElement>(
      ".convo-item"
    );
    if (!item || !item.dataset.id) return;
    void openConversation(item.dataset.id);
  });

  // Arrow-key navigation when the list itself is focused.
  dom.convoList.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveSelection(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      moveSelection(-1);
    } else if (event.key === "Enter" && state.activeId) {
      event.preventDefault();
      void openConversation(state.activeId);
    }
  });
}

async function refreshInbox(): Promise<void> {
  if (!state.authed) return;
  let summaries: ConversationSummary[];
  try {
    summaries = await adminListConversations();
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      showLoginGate();
    }
    return;
  }
  state.summaries = summaries;
  renderInbox();
}

/** The summaries that pass the current search + filter, in display order. */
function visibleSummaries(): ConversationSummary[] {
  const q = state.search;
  const filter = state.filter;
  return state.summaries.filter((s) => {
    if (filter === "attention" && !s.needs_attention) return false;
    if (filter === "unread" && s.unread_count <= 0) return false;
    if (!q) return true;
    const name = (s.conversation_name ?? "").toLowerCase();
    const preview = (s.last_content ?? "").toLowerCase();
    const id = s.conversation_id.toLowerCase();
    return name.includes(q) || preview.includes(q) || id.includes(q);
  });
}

function renderInbox(): void {
  const visible = visibleSummaries();

  // Count badge reflects the total number of conversations (not the filter).
  dom.convoCount.textContent = String(state.summaries.length);

  // Update the filter chips with live counts where the mockup shows them.
  updateFilterCounts();

  // Build rows. We rebuild the list each render (cheap; inbox is small) but
  // preserve the scroll position so polling doesn't jump the view.
  const scrollTop = dom.convoList.scrollTop;
  dom.convoList
    .querySelectorAll(".convo-item")
    .forEach((node) => node.remove());

  if (visible.length === 0) {
    dom.listEmpty.hidden = false;
    dom.listEmpty.textContent =
      state.summaries.length === 0
        ? "No conversations yet."
        : "No conversations match.";
    return;
  }
  dom.listEmpty.hidden = true;

  const frag = document.createDocumentFragment();
  for (const s of visible) {
    frag.appendChild(buildConvoItem(s));
  }
  // Insert before the (hidden) empty-state element so it stays last.
  dom.convoList.insertBefore(frag, dom.listEmpty);
  dom.convoList.scrollTop = scrollTop;
}

function updateFilterCounts(): void {
  const attention = state.summaries.filter((s) => s.needs_attention).length;
  const unread = state.summaries.filter((s) => s.unread_count > 0).length;
  const chips = dom.filterRow.querySelectorAll<HTMLElement>(".filter-chip");
  chips.forEach((chip) => {
    const mode = chip.dataset.filter;
    if (mode === "attention") {
      chip.innerHTML =
        `<span class="dot-y"></span>Needs you` +
        (attention > 0 ? ` · ${attention}` : "");
    } else if (mode === "unread") {
      chip.textContent = unread > 0 ? `Unread · ${unread}` : "Unread";
    }
  });
}

function buildConvoItem(s: ConversationSummary): HTMLElement {
  const item = document.createElement("div");
  item.className = "convo-item";
  item.dataset.id = s.conversation_id;
  item.setAttribute("role", "option");

  const isUnread = s.unread_count > 0;
  const isAttention = s.needs_attention;
  const isActive = s.conversation_id === state.activeId;
  item.classList.toggle("is-unread", isUnread);
  item.classList.toggle("is-attention", isAttention);
  item.classList.toggle("is-active", isActive);
  item.setAttribute("aria-selected", isActive ? "true" : "false");

  const name = displayName(s.conversation_name);
  const ini = s.initials || initials(s.conversation_name);
  const preview = previewText(s);
  const time = formatInboxTime(s.last_at);

  // Right-side status indicator: the "Needs you" badge wins for any attention
  // row (it persists until the thread is opened), then an unread dot, then a
  // subtle "read" check (matches the mockup + the §9 contract).
  let sideBadge: string;
  if (isAttention) {
    sideBadge = `<span class="badge badge--attention"><svg class="icon" style="width:11px;height:11px"><use href="/icons.svg#i-spark" /></svg> Needs you</span>`;
  } else if (isUnread) {
    sideBadge = `<span class="badge badge--dot"></span>`;
  } else {
    sideBadge = `<svg class="icon icon--sm" style="color:var(--positive)"><use href="/icons.svg#i-check2" /></svg>`;
  }

  item.innerHTML = `
    <span class="avatar-initials">${escapeHtml(ini)}</span>
    <div class="convo-main">
      <div class="convo-top"><span class="convo-name">${escapeHtml(name)}</span></div>
      <div class="convo-preview">${escapeHtml(preview)}</div>
    </div>
    <div class="convo-side">
      <span class="msg-time">${escapeHtml(time)}</span>
      ${sideBadge}
    </div>`;
  return item;
}

function displayName(name: string | null | undefined): string {
  const trimmed = (name ?? "").trim();
  return trimmed || "Anonymous";
}

function previewText(s: ConversationSummary): string {
  const body = (s.last_content ?? "").replace(/\s+/g, " ").trim();
  let prefix = "";
  if (s.last_role === "human") prefix = "You: ";
  else if (s.last_role === "avatar") prefix = "Avatar: ";
  const text = prefix + body;
  return text || "(no messages yet)";
}

// ---------------------------------------------------------------------------
// Selection (keyboard navigation)
// ---------------------------------------------------------------------------

function moveSelection(delta: number): void {
  const visible = visibleSummaries();
  if (visible.length === 0) return;
  const currentIndex = state.activeId
    ? visible.findIndex((s) => s.conversation_id === state.activeId)
    : -1;
  let nextIndex: number;
  if (currentIndex === -1) {
    nextIndex = delta > 0 ? 0 : visible.length - 1;
  } else {
    nextIndex = currentIndex + delta;
  }
  if (nextIndex < 0) nextIndex = 0;
  if (nextIndex > visible.length - 1) nextIndex = visible.length - 1;
  const target = visible[nextIndex];
  if (!target) return;
  if (target.conversation_id === state.activeId) {
    ensureRowVisible(target.conversation_id);
    return;
  }
  void openConversation(target.conversation_id);
}

function ensureRowVisible(conversationId: string): void {
  const row = dom.convoList.querySelector<HTMLElement>(
    `.convo-item[data-id="${cssEscape(conversationId)}"]`
  );
  row?.scrollIntoView({ block: "nearest" });
}

function cssEscape(value: string): string {
  // Conversation ids are UUIDs (hex + hyphens) so a minimal escape suffices,
  // but use the platform helper when available for safety.
  const fn = (window as unknown as { CSS?: { escape?: (s: string) => string } })
    .CSS?.escape;
  return fn ? fn(value) : value.replace(/["\\]/g, "\\$&");
}

// ---------------------------------------------------------------------------
// Thread open / render
// ---------------------------------------------------------------------------

function resetThreadState(): void {
  state.activeId = null;
  state.threadMessages = [];
  state.renderedIds = new Set<number>();
  state.lastSeenId = null;
  state.threadName = null;
  state.threadNeedsAttention = false;
  state.threadStartedAt = null;
}

async function openConversation(conversationId: string): Promise<void> {
  // Reflect selection immediately for snappy keyboard navigation.
  state.activeId = conversationId;
  markActiveRow(conversationId);
  ensureRowVisible(conversationId);
  enterDetailViewMobile();

  let convo: Conversation;
  try {
    convo = await adminOpenConversation(conversationId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      showLoginGate();
    }
    return;
  }

  // Opening cleared unread + needs_attention server-side; reflect locally so
  // the inbox row updates without waiting for the next poll.
  const summary = state.summaries.find(
    (s) => s.conversation_id === conversationId
  );
  if (summary) {
    summary.unread_count = 0;
    summary.needs_attention = false;
  }

  loadThread(convo);
  // Re-render the inbox so the just-opened row loses its unread/attention state
  // and gains is-active.
  renderInbox();
}

function loadThread(convo: Conversation): void {
  state.threadName = convo.conversation_name;
  state.threadMessages = [...convo.messages];
  state.renderedIds = new Set<number>();
  state.threadNeedsAttention = convo.messages.some((m) => m.needs_attention);
  state.threadStartedAt = convo.messages.length
    ? convo.messages[0].created_at
    : null;
  state.lastSeenId = convo.messages.length
    ? Math.max(...convo.messages.map((m) => m.id))
    : null;

  dom.threadEmpty.hidden = true;
  dom.threadView.hidden = false;

  renderThreadHeader();
  renderThreadMessages(state.threadMessages, true);
  updateAttentionUI();

  // Focus the composer and pin to the latest message.
  window.requestAnimationFrame(() => {
    dom.adminComposerInput.focus();
    scrollToBottom(dom.thread);
  });
  // A second pass after layout settles (fonts/images) keeps us at the bottom.
  window.setTimeout(() => scrollToBottom(dom.thread), 200);
}

function renderThreadHeader(): void {
  const name = displayName(state.threadName);
  dom.threadName.textContent = name;
  dom.threadInitials.textContent = initials(state.threadName);

  const shortId = shortConvId(state.activeId);
  const started = state.threadStartedAt
    ? formatDayTime(state.threadStartedAt)
    : "—";
  const count = state.threadMessages.length;
  dom.threadSub.textContent = `${shortId} · started ${started} · ${count} ${
    count === 1 ? "message" : "messages"
  }`;
}

function shortConvId(conversationId: string | null): string {
  if (!conversationId) return "conv_—";
  const compact = conversationId.replace(/-/g, "");
  return `conv_${compact.slice(0, 6)}`;
}

function markActiveRow(conversationId: string): void {
  dom.convoList.querySelectorAll<HTMLElement>(".convo-item").forEach((row) => {
    const active = row.dataset.id === conversationId;
    row.classList.toggle("is-active", active);
    row.setAttribute("aria-selected", active ? "true" : "false");
  });
}

/**
 * Render thread messages. When `replace` is true the inner list is cleared and
 * rebuilt; otherwise only messages whose ids aren't already rendered are
 * appended (used by the poll to surface new human/visitor/avatar rows).
 */
function renderThreadMessages(messages: Message[], replace: boolean): void {
  if (replace) {
    dom.threadInner.innerHTML = "";
    state.renderedIds = new Set<number>();
  }

  const toRender = messages.filter((m) => !state.renderedIds.has(m.id));
  if (toRender.length === 0) return;

  const frag = document.createDocumentFragment();
  let lastDayKey = currentLastDayKey();
  for (const msg of toRender) {
    const dayKey = dayBucket(msg.created_at);
    if (dayKey !== lastDayKey) {
      frag.appendChild(buildDaySeparator(msg.created_at));
      lastDayKey = dayKey;
    }
    frag.appendChild(buildMessage(msg));
    state.renderedIds.add(msg.id);
  }
  dom.threadInner.appendChild(frag);
}

/** The day bucket of the last already-rendered message, if any. */
function currentLastDayKey(): string | null {
  const rendered = state.threadMessages.filter((m) =>
    state.renderedIds.has(m.id)
  );
  if (rendered.length === 0) return null;
  const last = rendered[rendered.length - 1];
  return dayBucket(last.created_at);
}

function dayBucket(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "unknown";
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function buildDaySeparator(value: string): HTMLElement {
  const sep = document.createElement("div");
  sep.className = "day-sep";
  const label = document.createElement("span");
  label.className = "eyebrow";
  label.textContent = dayLabel(value);
  sep.appendChild(label);
  return sep;
}

function dayLabel(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (
    d.getFullYear() === yesterday.getFullYear() &&
    d.getMonth() === yesterday.getMonth() &&
    d.getDate() === yesterday.getDate()
  ) {
    return "Yesterday";
  }
  return d.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function buildMessage(msg: Message): HTMLElement {
  if (msg.role === "visitor") return buildVisitorMessage(msg);
  if (msg.role === "human") return buildHumanMessage(msg);
  return buildAvatarMessage(msg);
}

function buildVisitorMessage(msg: Message): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "msg msg--visitor";
  wrap.dataset.id = String(msg.id);

  const ini = initials(state.threadName);
  wrap.innerHTML = `
    <span class="avatar-initials">${escapeHtml(ini)}</span>
    <div class="msg-body">
      <div class="msg-meta"><span class="msg-time">${escapeHtml(
        formatTime(msg.created_at)
      )}</span></div>
      <div class="bubble">${renderMarkdown(msg.content)}</div>
    </div>`;
  return wrap;
}

function buildAvatarMessage(msg: Message): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "msg msg--avatar";
  wrap.dataset.id = String(msg.id);

  const statuses = avatarStatusHtml(msg);
  wrap.innerHTML = `
    <div class="avatar avatar-twin" style="background-image:url('${TWIN_FILE}')"></div>
    <div class="msg-body">
      <div class="msg-meta"><span class="msg-name">Avatar</span><span class="msg-time">${escapeHtml(
        formatTime(msg.created_at)
      )}</span></div>
      ${statuses}
      <div class="bubble">${renderMarkdown(msg.content)}</div>
    </div>`;
  return wrap;
}

/** Tool-status / instant-tag rows for an avatar message (from tool_calls). */
function avatarStatusHtml(msg: Message): string {
  const tc = msg.tool_calls;
  if (!tc) return "";

  // Instant (Qn) answers carry {instant: n}.
  if (typeof tc.instant === "number") {
    return `<div class="msg-meta"><span class="instant-tag">instant · Q${tc.instant}</span></div>`;
  }

  // Streamed answers carry {tools: [{name, detail}]}.
  if (Array.isArray(tc.tools) && tc.tools.length > 0) {
    const lines = tc.tools
      .map((t) => {
        const icon = toolIcon(t.name);
        const detail = t.detail ? ` · ${escapeHtml(t.detail)}` : "";
        return `<div class="tool-status is-done"><svg class="icon"><use href="/icons.svg#${icon}" /></svg> ${escapeHtml(
          t.name
        )}${detail}</div>`;
      })
      .join("");
    return `<div class="tool-statuses">${lines}</div>`;
  }
  return "";
}

function buildHumanMessage(msg: Message): HTMLElement {
  const wrap = document.createElement("div");
  wrap.className = "msg msg--human";
  wrap.dataset.id = String(msg.id);

  // In admin, the human/own message reads "You · sent to visitor" per the
  // mockup (this is the owner's own dashboard).
  wrap.innerHTML = `
    <div class="avatar avatar-human" style="background-image:url('${HUMAN_FILE}')">
      <span class="spark-badge"><svg class="icon"><use href="/icons.svg#i-spark" /></svg></span>
    </div>
    <div class="msg-body">
      <div class="msg-meta">
        <span class="human-tag"><svg class="icon"><use href="/icons.svg#i-live" /></svg> You · sent to visitor</span>
        <span class="msg-time">${escapeHtml(formatTime(msg.created_at))}</span>
      </div>
      <div class="bubble">${renderMarkdown(msg.content)}</div>
    </div>`;
  return wrap;
}

// ---------------------------------------------------------------------------
// Attention flag / resolve
// ---------------------------------------------------------------------------

function updateAttentionUI(): void {
  dom.attnFlag.hidden = !state.threadNeedsAttention;
}

function wireThread(): void {
  dom.resolveBtn.addEventListener("click", async () => {
    if (!state.activeId) return;
    const id = state.activeId;
    dom.resolveBtn.disabled = true;
    try {
      await adminResolve(id);
      state.threadNeedsAttention = false;
      updateAttentionUI();
      const summary = state.summaries.find((s) => s.conversation_id === id);
      if (summary) summary.needs_attention = false;
      renderInbox();
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) showLoginGate();
    } finally {
      dom.resolveBtn.disabled = false;
    }
  });

  // Composer: auto-grow, Enter sends, Shift+Enter newline.
  const ta = dom.adminComposerInput;
  ta.addEventListener("input", () => autoGrow(ta));
  ta.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void sendAdminMessage();
    }
  });
  dom.adminSendBtn.addEventListener("click", () => {
    void sendAdminMessage();
  });

  // Mobile back controls return to the inbox.
  dom.mobileBackBtn.addEventListener("click", exitDetailViewMobile);
  dom.threadBackBtn.addEventListener("click", exitDetailViewMobile);
}

function autoGrow(ta: HTMLTextAreaElement): void {
  ta.style.height = "auto";
  ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
}

async function sendAdminMessage(): Promise<void> {
  if (!state.activeId) return;
  const content = dom.adminComposerInput.value.trim();
  if (!content) return;
  const id = state.activeId;

  dom.adminSendBtn.disabled = true;
  dom.adminComposerInput.disabled = true;
  try {
    const row = await adminPostMessage(id, content);
    // Insert into the open thread (the Avatar does NOT react).
    appendMessageToThread(row);

    // Update the inbox preview/order for this conversation.
    const summary = state.summaries.find((s) => s.conversation_id === id);
    if (summary) {
      summary.last_role = row.role;
      summary.last_content = row.content;
      summary.last_at = row.created_at;
      summary.message_count += 1;
      // A human reply doesn't add unread; move it to the top.
      state.summaries = [
        summary,
        ...state.summaries.filter((s) => s.conversation_id !== id),
      ];
    }
    renderInbox();

    dom.adminComposerInput.value = "";
    autoGrow(dom.adminComposerInput);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      showLoginGate();
      return;
    }
    // Keep the typed text so the owner can retry.
  } finally {
    dom.adminSendBtn.disabled = false;
    dom.adminComposerInput.disabled = false;
    window.requestAnimationFrame(() => dom.adminComposerInput.focus());
  }
}

/** Append a single message to the open thread (de-duped) and pin to bottom. */
function appendMessageToThread(msg: Message): void {
  if (state.renderedIds.has(msg.id)) return;
  state.threadMessages.push(msg);
  if (state.lastSeenId == null || msg.id > state.lastSeenId) {
    state.lastSeenId = msg.id;
  }
  renderThreadMessages([msg], false);
  renderThreadHeader();
  scrollToBottom(dom.thread, true);
}

// ---------------------------------------------------------------------------
// Mobile master/detail
// ---------------------------------------------------------------------------

function isMobile(): boolean {
  return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`).matches;
}

function enterDetailViewMobile(): void {
  if (isMobile()) dom.dashboard.classList.add("show-detail");
}

function exitDetailViewMobile(): void {
  dom.dashboard.classList.remove("show-detail");
  window.requestAnimationFrame(() => dom.searchInput.focus());
}

// ---------------------------------------------------------------------------
// Global keyboard (arrow navigation from anywhere except the textarea)
// ---------------------------------------------------------------------------

function wireGlobalKeys(): void {
  document.addEventListener("keydown", (event) => {
    if (!state.authed || dom.dashboard.hidden) return;
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;

    const target = event.target as HTMLElement | null;
    // Don't hijack arrows while typing in the composer or any input/textarea.
    if (target) {
      const tag = target.tagName;
      if (tag === "TEXTAREA" || tag === "INPUT" || target.isContentEditable) {
        return;
      }
    }
    // The list handles its own arrows when focused; only act globally when it
    // isn't the active element (avoids double-moving).
    if (document.activeElement === dom.convoList) return;

    event.preventDefault();
    moveSelection(event.key === "ArrowDown" ? 1 : -1);
  });
}

// ---------------------------------------------------------------------------
// Polling — inbox + open thread (~10s)
// ---------------------------------------------------------------------------

function startPolling(): void {
  stopPolling();
  pollTimer = window.setInterval(() => {
    void poll();
  }, POLL_INTERVAL_MS);
}

function stopPolling(): void {
  if (pollTimer != null) {
    window.clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function poll(): Promise<void> {
  if (!state.authed || dom.dashboard.hidden) return;
  if (document.hidden) return; // skip while the tab is backgrounded
  await refreshInbox();
  if (state.activeId) {
    await pollOpenThread(state.activeId);
  }
}

/**
 * Refresh the open thread by re-fetching the full conversation and appending
 * any new rows. We do NOT call adminOpenConversation here (that would re-clear
 * read/attention every poll); instead we re-list via the same endpoint the
 * inbox already used and reconcile new messages. Because adminOpenConversation
 * is the only thread fetch available to admin and it has side effects, we keep
 * the poll cheap by only re-opening when the inbox summary reports new activity
 * for the active conversation.
 */
async function pollOpenThread(conversationId: string): Promise<void> {
  const summary = state.summaries.find(
    (s) => s.conversation_id === conversationId
  );
  if (!summary) return;

  // If the inbox shows more messages than we've rendered, or fresh attention,
  // re-open to pull the new rows. Opening also re-clears read/attention, which
  // is correct: the owner is actively viewing this thread.
  const renderedCount = state.threadMessages.length;
  const hasNew =
    summary.message_count > renderedCount ||
    (summary.needs_attention && !state.threadNeedsAttention) ||
    summary.unread_count > 0;
  if (!hasNew) return;

  let convo: Conversation;
  try {
    convo = await adminOpenConversation(conversationId);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) showLoginGate();
    return;
  }

  // Reconcile: append only messages we haven't rendered yet (de-dupe by id).
  const known = state.renderedIds;
  const fresh = convo.messages.filter((m) => !known.has(m.id));
  if (fresh.length > 0) {
    const atBottom = isScrolledToBottom(dom.thread);
    for (const m of fresh) state.threadMessages.push(m);
    state.threadName = convo.conversation_name;
    if (!state.threadStartedAt && convo.messages.length) {
      state.threadStartedAt = convo.messages[0].created_at;
    }
    state.lastSeenId = Math.max(
      state.lastSeenId ?? 0,
      ...convo.messages.map((m) => m.id)
    );
    renderThreadMessages(fresh, false);
    renderThreadHeader();
    if (atBottom) scrollToBottom(dom.thread, true);
  }

  // Opening cleared attention server-side; reflect that locally.
  state.threadNeedsAttention = false;
  updateAttentionUI();
  summary.needs_attention = false;
  summary.unread_count = 0;
  renderInbox();
}

function isScrolledToBottom(elm: HTMLElement, slackPx = 80): boolean {
  return elm.scrollHeight - elm.scrollTop - elm.clientHeight <= slackPx;
}

// Pause/resume polling with tab visibility to avoid needless requests.
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && state.authed) {
    void poll();
  }
});

// ---------------------------------------------------------------------------
// Go
// ---------------------------------------------------------------------------

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
