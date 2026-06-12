// Visitor screen logic. Drives the chat experience in index.html against the
// shared API client (api.ts), the theme module (theme.ts) and the DOM helpers
// (util.ts, markdown.ts, ./render.ts). Behaviour authority: SPEC.md "Interactive
// Chat Experience" + docs/ARCHITECTURE.md §9 + design-system/docs/ux-flows.md A–F.
//
// Owner name is ALWAYS read from /api/config — never hardcoded.

import {
  ApiError,
  getConfig,
  getConversation,
  postInstant,
  streamChat,
  type ChatRequest,
  type Message,
} from "../api";
import { attachThemeToggle, initTheme } from "../theme";
import {
  getCookie,
  setCookie,
  deleteCookie,
  initials as toInitials,
  scrollToBottom,
  uuid,
} from "../util";
import { renderMarkdown } from "../markdown";
import {
  buildAvatarMessage,
  buildMessageFromRow,
  buildToolStatusRow,
  buildVisitorMessage,
  type AvatarMessageNodes,
} from "./render";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const COOKIE_NAME = "avatar_conversation";
const COOKIE_DAYS = 365;
const QN_RE = /^q(\d{1,2})$/i;

const POLL_FAST_MS = 10_000;
const POLL_SLOW_MS = 60_000;
const POLL_SLOWDOWN_AFTER_MS = 5 * 60_000; // ease to slow cadence after 5 quiet min

const RATE_LIMIT_COPY = "You're sending messages too quickly — give it a moment.";
const GENERIC_ERROR_COPY = "Something went wrong. Please try again.";

// ---------------------------------------------------------------------------
// Element handles
// ---------------------------------------------------------------------------

function el<T extends HTMLElement = HTMLElement>(id: string): T {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing required element #${id}`);
  return node as T;
}

const brandSub = el<HTMLSpanElement>("brandSub");
const nameInput = el<HTMLInputElement>("nameInput");
const nameInputMobile = el<HTMLInputElement>("nameInputMobile");
const keepChat = el<HTMLInputElement>("keepChat");
const keepChatMobile = el<HTMLInputElement>("keepChatMobile");
const resetBtn = el<HTMLButtonElement>("resetBtn");
const resetBtnMobile = el<HTMLButtonElement>("resetBtnMobile");

const convo = el<HTMLDivElement>("convo");
const intro = el<HTMLDivElement>("intro");
const introHeading = el<HTMLHeadingElement>("introHeading");
const introBlurb = el<HTMLParagraphElement>("introBlurb");
const suggestRow = el<HTMLDivElement>("suggestRow");
const threadMessages = el<HTMLDivElement>("threadMessages");
const typingIndicator = el<HTMLDivElement>("typingIndicator");

const composerBanner = el<HTMLDivElement>("composerBanner");
const composerInput = el<HTMLTextAreaElement>("composerInput");
const sendBtn = el<HTMLButtonElement>("sendBtn");

// ---------------------------------------------------------------------------
// App state
// ---------------------------------------------------------------------------

let ownerName = "the owner";
let conversationId = "";
/** The greatest message id we've rendered — the poll watermark + de-dupe key. */
let lastSeenId = 0;
/** Ids already rendered, so optimistic + polled rows never double-render. */
const renderedIds = new Set<number>();
/** True while a send (instant or stream) is in flight. */
let sending = false;
/** Abort controller for the in-flight chat stream (cancelled on reset). */
let streamAbort: AbortController | null = null;

// Polling cadence state.
let pollTimer: number | null = null;
let pollInterval = POLL_FAST_MS;
let lastActivityAt = Date.now();
let polling = false;

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function currentName(): string {
  return nameInput.value.trim();
}

function visitorInitials(): string {
  const name = currentName();
  // When the visitor hasn't given a name, label their own bubble "Anon" rather
  // than a bare "?" (the admin inbox keeps its own "?" via db._initials).
  return name ? toInitials(name) : "Anon";
}

function hasThreadMessages(): boolean {
  return threadMessages.childElementCount > 0;
}

/** Hide the hero once the thread has any content (per ux-flows A). */
function syncIntroVisibility(): void {
  intro.style.display = hasThreadMessages() ? "none" : "";
}

function setTyping(on: boolean): void {
  typingIndicator.style.display = on ? "" : "none";
  if (on) scrollConvoToBottom();
}

function scrollConvoToBottom(smooth = false): void {
  scrollToBottom(convo, smooth);
}

function showBanner(text: string, isError = false): void {
  composerBanner.textContent = text;
  composerBanner.classList.toggle("is-error", isError);
  composerBanner.hidden = false;
}

function hideBanner(): void {
  composerBanner.hidden = true;
  composerBanner.classList.remove("is-error");
  composerBanner.textContent = "";
}

function focusComposer(): void {
  // preventScroll keeps the viewport pinned to the latest message after sending.
  composerInput.focus({ preventScroll: true });
}

/** Auto-grow the composer textarea to fit its content (capped by CSS max-height). */
function autoGrowComposer(): void {
  composerInput.style.height = "auto";
  composerInput.style.height = `${composerInput.scrollHeight}px`;
}

/** Track a rendered row so polling won't duplicate it; advance the watermark. */
function trackRendered(id: number | null | undefined): void {
  if (id == null) return;
  renderedIds.add(id);
  if (id > lastSeenId) lastSeenId = id;
}

// ---------------------------------------------------------------------------
// Config / personalization
// ---------------------------------------------------------------------------

async function loadConfig(): Promise<void> {
  try {
    const cfg = await getConfig();
    if (cfg && cfg.owner_name) ownerName = cfg.owner_name;
  } catch {
    // Keep the neutral default; the app still works without personalization.
  }
  applyOwnerName();
}

function applyOwnerName(): void {
  // Header subtitle — "<owner> · digital twin".
  brandSub.textContent = `${ownerName} · digital twin`;
  // Page title.
  document.title = `Avatar — ${ownerName}'s digital twin`;
  // Hero heading — keep the <em>digital twin</em> emphasis from the markup.
  introHeading.innerHTML =
    `I'm ${escapeForHtml(ownerName)}'s <em>digital twin</em>.<br />` +
    `Ask me anything — and the real ${escapeForHtml(ownerName)} might just chime in.`;
  introBlurb.textContent =
    `I know ${ownerName}'s background and work, and I can put you in touch with ` +
    `${ownerName} directly.`;
  // Composer placeholder references the owner.
  composerInput.placeholder = `Message ${ownerName}'s twin…  (type "Q2" for an instant answer)`;
}

function escapeForHtml(value: string): string {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Conversation id / cookie lifecycle
// ---------------------------------------------------------------------------

function mintConversationId(): string {
  // crypto.randomUUID via the util helper (with a safe fallback).
  return uuid();
}

function persistConversationId(): void {
  if (keepChat.checked) {
    setCookie(COOKIE_NAME, conversationId, { days: COOKIE_DAYS, sameSite: "Lax" });
  } else {
    deleteCookie(COOKIE_NAME);
  }
}

/**
 * Initialise the conversation: if Keep chat is on and a cookie exists, restore
 * that thread; otherwise mint a new id and (if Keep chat on) set the cookie.
 */
async function initConversation(): Promise<void> {
  const existing = keepChat.checked ? getCookie(COOKIE_NAME) : null;
  if (existing) {
    conversationId = existing;
    await restoreThread();
  } else {
    conversationId = mintConversationId();
    persistConversationId();
  }
}

/** Fetch and render the full stored thread (Keep-chat restore, ux-flows B). */
async function restoreThread(): Promise<void> {
  try {
    const convoData = await getConversation(conversationId);
    const messages = convoData.messages ?? [];
    // Adopt a name the owner/visitor used earlier so initials match on restore.
    if (!currentName() && convoData.conversation_name) {
      setNameFields(convoData.conversation_name);
    }
    for (const row of messages) renderRow(row);
    syncIntroVisibility();
    if (messages.length) scrollConvoToBottom();
  } catch {
    // A stale/unknown id just yields an empty thread — start fresh visually.
  }
}

/** Render one persisted row, de-duped by id. */
function renderRow(row: Message): void {
  if (renderedIds.has(row.id)) return;
  const node = buildMessageFromRow(row, ownerName, visitorInitials());
  if (!node) return;
  threadMessages.appendChild(node);
  trackRendered(row.id);
}

function resetConversation(): void {
  // Cancel any in-flight stream and clear all state + view.
  streamAbort?.abort();
  streamAbort = null;
  sending = false;
  setTyping(false);
  hideBanner();
  threadMessages.replaceChildren();
  renderedIds.clear();
  lastSeenId = 0;
  conversationId = mintConversationId();
  persistConversationId();
  syncIntroVisibility();
  resetPollCadence();
  focusComposer();
}

// ---------------------------------------------------------------------------
// Control mirroring (desktop <-> mobile)
// ---------------------------------------------------------------------------

function setNameFields(value: string): void {
  nameInput.value = value;
  nameInputMobile.value = value;
}

function wireMirroredControls(): void {
  // Name field: keep both inputs in sync both directions.
  nameInput.addEventListener("input", () => {
    nameInputMobile.value = nameInput.value;
  });
  nameInputMobile.addEventListener("input", () => {
    nameInput.value = nameInputMobile.value;
  });

  // Keep-chat switch: mirror, and (un)set the cookie immediately so toggling it
  // off forgets the thread and toggling it on remembers the current id.
  const onKeepChange = (source: HTMLInputElement, mirror: HTMLInputElement) => {
    mirror.checked = source.checked;
    persistConversationId();
  };
  keepChat.addEventListener("change", () => onKeepChange(keepChat, keepChatMobile));
  keepChatMobile.addEventListener("change", () =>
    onKeepChange(keepChatMobile, keepChat)
  );

  // Reset buttons (both mirror the same action).
  resetBtn.addEventListener("click", resetConversation);
  resetBtnMobile.addEventListener("click", resetConversation);
}

// ---------------------------------------------------------------------------
// Sending
// ---------------------------------------------------------------------------

function buildRequest(message: string): ChatRequest {
  const req: ChatRequest = { conversation_id: conversationId, message };
  const name = currentName();
  if (name) req.name = name;
  return req;
}

/** Append an optimistic visitor bubble for the message just submitted. */
function appendVisitorBubble(message: string): void {
  const node = buildVisitorMessage({
    initialsText: visitorInitials(),
    content: message,
  });
  threadMessages.appendChild(node);
  syncIntroVisibility();
  scrollConvoToBottom(true);
}

/**
 * Submit a message. Routes Qn shortcuts to /api/instant (with a stream fallback
 * when the FAQ number isn't found) and everything else to the streaming chat.
 */
async function submitMessage(rawMessage: string): Promise<void> {
  const message = rawMessage.replace(/\s+$/g, "");
  if (!message.trim() || sending) return;

  sending = true;
  hideBanner();
  noteActivity();

  appendVisitorBubble(message);

  const qn = message.trim().match(QN_RE);
  try {
    if (qn) {
      const handled = await sendInstant(message);
      if (!handled) await sendStreaming(message);
    } else {
      await sendStreaming(message);
    }
  } finally {
    sending = false;
    focusComposer();
  }
}

/**
 * Try the Qn instant answer. Returns true if the FAQ was found and rendered;
 * false (found:false) means the caller should fall back to streaming.
 */
async function sendInstant(message: string): Promise<boolean> {
  try {
    const result = await postInstant(buildRequest(message));
    if (!result.found) return false;
    // The visitor row was persisted server-side with this id — adopt it so the
    // poll doesn't re-render the optimistic bubble.
    trackRendered(result.visitor_id);

    const nodes = buildAvatarMessage({ instantQuestion: result.question_number });
    nodes.bubble.innerHTML = renderMarkdown(result.content);
    threadMessages.appendChild(nodes.msg);
    trackRendered(result.avatar_id);
    syncIntroVisibility();
    scrollConvoToBottom(true);
    return true;
  } catch (err) {
    handleSendError(err);
    // On a hard error (e.g. rate limit) do NOT fall through to streaming.
    return true;
  }
}

/** Stream an avatar reply over SSE, rendering tokens + tool status live. */
async function sendStreaming(message: string): Promise<void> {
  const nodes = buildAvatarMessage();
  let appended = false;
  let acc = "";
  let errored = false;
  // Track in-flight tool rows so a "done" event can collapse the right one.
  const toolRows = new Map<string, HTMLDivElement>();

  const ensureAppended = () => {
    if (!appended) {
      threadMessages.appendChild(nodes.msg);
      appended = true;
      syncIntroVisibility();
    }
  };

  setTyping(true);
  streamAbort = new AbortController();

  try {
    await streamChat(
      buildRequest(message),
      {
        onToken: (text) => {
          ensureAppended();
          // First real token: drop the typing indicator, the bubble takes over.
          setTyping(false);
          acc += text;
          nodes.bubble.innerHTML = renderMarkdown(acc);
          scrollConvoToBottom();
        },
        onTool: (tool) => {
          ensureAppended();
          handleToolStatus(nodes, toolRows, tool);
          scrollConvoToBottom();
        },
        onDone: (messageId) => {
          trackRendered(messageId);
        },
        onError: (msg) => {
          errored = true;
          renderStreamError(nodes, ensureAppended, msg);
        },
      },
      streamAbort.signal
    );
  } catch (err) {
    // streamChat throws only for the 429 rate-limit case.
    errored = true;
    if (err instanceof ApiError && err.isRateLimited) {
      renderStreamError(nodes, ensureAppended, RATE_LIMIT_COPY, false);
      showBanner(RATE_LIMIT_COPY);
    } else {
      renderStreamError(nodes, ensureAppended, GENERIC_ERROR_COPY, true);
    }
  } finally {
    setTyping(false);
    streamAbort = null;
    // If the stream produced nothing at all and didn't error, drop the empty
    // shell so we don't leave a blank avatar bubble behind.
    if (!appended && !errored) {
      nodes.msg.remove();
    }
    scrollConvoToBottom();
  }
}

/** Add or collapse a tool-status row for a calling/done event. */
function handleToolStatus(
  nodes: AvatarMessageNodes,
  toolRows: Map<string, HTMLDivElement>,
  tool: { phase: "calling" | "done"; name: string; detail?: string | null }
): void {
  if (tool.phase === "calling") {
    const row = buildToolStatusRow(tool.name, tool.detail ?? null, false);
    nodes.toolStatuses.appendChild(row);
    toolRows.set(tool.name, row);
  } else {
    const done = buildToolStatusRow(tool.name, tool.detail ?? null, true);
    const existing = toolRows.get(tool.name);
    if (existing && existing.parentElement) {
      existing.replaceWith(done);
    } else {
      nodes.toolStatuses.appendChild(done);
    }
    toolRows.delete(tool.name);
  }
}

/** Render an error inside the avatar bubble (friendly, non-crashing). */
function renderStreamError(
  nodes: AvatarMessageNodes,
  ensureAppended: () => void,
  text: string,
  isError = true
): void {
  ensureAppended();
  setTyping(false);
  nodes.bubble.innerHTML = renderMarkdown(text);
  if (isError) showBanner(text, true);
  scrollConvoToBottom();
}

/** Map a thrown error from the instant path to friendly UI. */
function handleSendError(err: unknown): void {
  if (err instanceof ApiError && err.isRateLimited) {
    showBanner(RATE_LIMIT_COPY);
    appendInfoAvatarBubble(RATE_LIMIT_COPY);
    return;
  }
  showBanner(GENERIC_ERROR_COPY, true);
  appendInfoAvatarBubble(GENERIC_ERROR_COPY);
}

/** Append a non-persisted avatar bubble carrying an info/error message. */
function appendInfoAvatarBubble(text: string): void {
  const nodes = buildAvatarMessage();
  nodes.bubble.innerHTML = renderMarkdown(text);
  threadMessages.appendChild(nodes.msg);
  syncIntroVisibility();
  scrollConvoToBottom(true);
}

// ---------------------------------------------------------------------------
// Polling for the human (ux-flows E)
// ---------------------------------------------------------------------------

function noteActivity(): void {
  lastActivityAt = Date.now();
  if (pollInterval !== POLL_FAST_MS) {
    pollInterval = POLL_FAST_MS;
    schedulePoll();
  }
}

function resetPollCadence(): void {
  lastActivityAt = Date.now();
  pollInterval = POLL_FAST_MS;
  schedulePoll();
}

function schedulePoll(): void {
  if (pollTimer != null) window.clearTimeout(pollTimer);
  pollTimer = window.setTimeout(runPoll, pollInterval);
}

async function runPoll(): Promise<void> {
  // Skip while a send is mid-flight to avoid racing the optimistic render.
  if (!polling && !sending && conversationId) {
    polling = true;
    try {
      const convoData = await getConversation(conversationId, lastSeenId || null);
      const rows = convoData.messages ?? [];
      let appendedAny = false;
      for (const row of rows) {
        if (renderedIds.has(row.id)) continue;
        // The visitor only ever sees their own thread, so every `visitor` row is
        // one this browser already rendered optimistically. Adopt its id (so the
        // watermark advances) but don't re-render it. This also covers the case
        // where a stream errored before `done`, leaving the visitor row untracked.
        if (row.role === "visitor") {
          trackRendered(row.id);
          continue;
        }
        // Avatar rows can also arrive via poll only if a stream finished without
        // delivering `done` (rare); render them so the reply isn't lost.
        renderRow(row);
        appendedAny = true;
        // Human messages arriving via poll are the designed live moment.
        if (row.role === "human") noteActivity();
      }
      if (appendedAny) {
        syncIntroVisibility();
        scrollConvoToBottom(true);
      }
    } catch {
      // Transient poll failures are non-fatal; try again next tick.
    } finally {
      polling = false;
    }
  }

  // Ease to the slow cadence after a quiet stretch.
  if (
    pollInterval === POLL_FAST_MS &&
    Date.now() - lastActivityAt >= POLL_SLOWDOWN_AFTER_MS
  ) {
    pollInterval = POLL_SLOW_MS;
  }
  schedulePoll();
}

// ---------------------------------------------------------------------------
// Composer + suggestion wiring
// ---------------------------------------------------------------------------

function sendFromComposer(): void {
  const message = composerInput.value;
  if (!message.trim()) return;
  composerInput.value = "";
  autoGrowComposer();
  void submitMessage(message);
}

function wireComposer(): void {
  composerInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendFromComposer();
    }
  });
  composerInput.addEventListener("input", autoGrowComposer);
  sendBtn.addEventListener("click", () => {
    sendFromComposer();
    focusComposer();
  });

  // Suggestion chips submit their prompt immediately on click.
  suggestRow.addEventListener("click", (e) => {
    const origin = e.target;
    if (!(origin instanceof Element)) return;
    const target = origin.closest<HTMLElement>("[data-suggest]");
    if (!target) return;
    const prompt = target.dataset.suggest ?? target.textContent ?? "";
    if (prompt.trim()) {
      void submitMessage(prompt.trim());
      focusComposer();
    }
  });
}

// ---------------------------------------------------------------------------
// Deep link ?q=N — submit Q{N} on arrival, then strip the param.
// ---------------------------------------------------------------------------

function consumeDeepLink(): void {
  const params = new URLSearchParams(window.location.search);
  const q = params.get("q");
  if (q == null) return;
  // Always clear the param from the URL so a refresh doesn't re-submit.
  params.delete("q");
  const search = params.toString();
  const newUrl =
    window.location.pathname + (search ? `?${search}` : "") + window.location.hash;
  window.history.replaceState({}, "", newUrl);

  const n = q.trim();
  if (/^\d{1,2}$/.test(n)) {
    void submitMessage(`Q${n}`);
  }
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  initTheme();
  attachThemeToggle("themeToggle");

  wireMirroredControls();
  wireComposer();
  autoGrowComposer();

  // Composer must autofocus on load (hard requirement).
  focusComposer();

  await loadConfig();
  await initConversation();

  syncIntroVisibility();

  // Start polling for the human; then handle a ?q=N deep link (after the thread
  // is in place so the optimistic bubble lands in the right spot).
  resetPollCadence();
  consumeDeepLink();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => void main());
} else {
  void main();
}
