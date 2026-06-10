// Typed fetch client for the Avatar backend. This is the SHARED CONTRACT used by
// both the visitor and admin screens — keep names, routes and shapes in lockstep
// with docs/ARCHITECTURE.md §8/§9. All requests are same-origin (in dev, Vite
// proxies /api and /admin to :8000), so credentials default to same-origin and
// the admin session cookie rides along automatically.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type Role = "visitor" | "avatar" | "human";

/** A single persisted conversation row, as returned by the API. */
export interface Message {
  id: number;
  role: Role;
  content: string;
  created_at: string;
  /** Tool-use summary or instant-answer marker; null when none. */
  tool_calls: ToolCalls | null;
  needs_attention: boolean;
  read: boolean;
}

/** Loose shape for the persisted tool_calls JSON (forward-compatible). */
export interface ToolCalls {
  /** Present on instant (Qn) avatar rows: the FAQ number answered. */
  instant?: number;
  /** Present on streamed avatar rows: the tools the agent invoked. */
  tools?: ToolCallSummary[];
  [key: string]: unknown;
}

export interface ToolCallSummary {
  name: string;
  detail?: string | null;
}

/** Full conversation payload (public fetch + admin open). */
export interface Conversation {
  conversation_id: string;
  conversation_name: string | null;
  messages: Message[];
}

/** Inbox summary row for the admin sidebar. */
export interface ConversationSummary {
  conversation_id: string;
  conversation_name: string | null;
  last_role: Role;
  last_content: string;
  last_at: string;
  message_count: number;
  unread_count: number;
  needs_attention: boolean;
  initials: string;
}

export interface AppConfig {
  owner_name: string;
}

/** Result of POST /api/instant. */
export type InstantResult =
  | {
      found: true;
      question_number: number;
      content: string;
      avatar_id: number;
      visitor_id: number;
    }
  | { found: false };

export interface ChatRequest {
  conversation_id: string;
  name?: string;
  message: string;
}

// ---------------------------------------------------------------------------
// SSE stream piece types (the normalized wire frames from /api/chat)
// ---------------------------------------------------------------------------

export type StreamPiece =
  | { type: "start" }
  | { type: "token"; text: string }
  | {
      type: "tool";
      phase: "calling" | "done";
      name: string;
      detail?: string | null;
    }
  | { type: "done"; message_id: number }
  | { type: "error"; message: string };

export interface StreamHandlers {
  /** A text delta to append to the avatar bubble. */
  onToken?: (text: string) => void;
  /** A tool status update (calling -> done). */
  onTool?: (tool: {
    phase: "calling" | "done";
    name: string;
    detail?: string | null;
  }) => void;
  /** Stream finished cleanly; carries the persisted avatar row id. */
  onDone?: (messageId: number) => void;
  /** A server-sent or transport error. After this, the stream is finished. */
  onError?: (message: string) => void;
}

// ---------------------------------------------------------------------------
// Error type
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  constructor(status: number, message: string, body: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
  /** True for HTTP 429 (per-conversation rate limit). */
  get isRateLimited(): boolean {
    return this.status === 429;
  }
  /** True for HTTP 401 (admin not authenticated). */
  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

// ---------------------------------------------------------------------------
// Low-level helpers
// ---------------------------------------------------------------------------

const JSON_HEADERS = { "Content-Type": "application/json" } as const;

async function parseBody(res: Response): Promise<unknown> {
  const ct = res.headers.get("content-type") ?? "";
  if (ct.includes("application/json")) {
    try {
      return await res.json();
    } catch {
      return null;
    }
  }
  try {
    return await res.text();
  } catch {
    return null;
  }
}

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(input, { credentials: "same-origin", ...init });
  } catch (err) {
    throw new ApiError(0, `Network error: ${(err as Error).message}`, null);
  }
  const body = await parseBody(res);
  if (!res.ok) {
    const message =
      (body && typeof body === "object" && "error" in body
        ? String((body as Record<string, unknown>).error)
        : null) ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, message, body);
  }
  return body as T;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** GET /api/config — owner name for headers/subtitle/page title. */
export function getConfig(): Promise<AppConfig> {
  return requestJson<AppConfig>("/api/config");
}

/**
 * GET /api/conversation — full thread (no afterId) for Keep-chat restore, or
 * only-newer rows (afterId = last seen id) for the human poll.
 */
export function getConversation(
  conversationId: string,
  afterId?: number | null
): Promise<Conversation> {
  const params = new URLSearchParams({ conversation_id: conversationId });
  if (afterId != null) params.set("after_id", String(afterId));
  return requestJson<Conversation>(`/api/conversation?${params.toString()}`);
}

/**
 * POST /api/instant — the Qn shortcut. Returns {found:false} for non-Qn input
 * (caller then falls back to streamChat).
 */
export function postInstant(body: ChatRequest): Promise<InstantResult> {
  return requestJson<InstantResult>("/api/instant", {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
  });
}

/**
 * POST /api/chat — streams the avatar reply over SSE (plain `data:` frames,
 * separated by blank lines). Parsed with fetch + ReadableStream. The returned
 * promise resolves when the stream is fully consumed (done or error already
 * dispatched to handlers). A 429 throws an ApiError before any streaming.
 *
 * Pass an AbortSignal to cancel an in-flight stream (e.g. on Reset/navigation).
 */
export async function streamChat(
  body: ChatRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  let res: Response;
  try {
    res = await fetch("/api/chat", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify(body),
      credentials: "same-origin",
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    const msg = `Network error: ${(err as Error).message}`;
    handlers.onError?.(msg);
    return;
  }

  if (!res.ok) {
    const errBody = await parseBody(res);
    const message =
      (errBody && typeof errBody === "object" && "error" in errBody
        ? String((errBody as Record<string, unknown>).error)
        : null) ?? `Chat failed (${res.status})`;
    // Surface 429 as a thrown ApiError so callers can show the rate-limit copy.
    if (res.status === 429) {
      throw new ApiError(429, message, errBody);
    }
    handlers.onError?.(message);
    return;
  }

  if (!res.body) {
    handlers.onError?.("Streaming is not supported in this browser.");
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (piece: StreamPiece) => {
    switch (piece.type) {
      case "start":
        break;
      case "token":
        if (piece.text) handlers.onToken?.(piece.text);
        break;
      case "tool":
        handlers.onTool?.({
          phase: piece.phase,
          name: piece.name,
          detail: piece.detail ?? null,
        });
        break;
      case "done":
        handlers.onDone?.(piece.message_id);
        break;
      case "error":
        handlers.onError?.(piece.message);
        break;
    }
  };

  const handleFrame = (frame: string) => {
    // An SSE frame is one or more lines; we only emit `data:` lines.
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).replace(/^ /, ""));
      }
    }
    if (dataLines.length === 0) return;
    const payload = dataLines.join("\n").trim();
    if (!payload || payload === "[DONE]") return;
    try {
      dispatch(JSON.parse(payload) as StreamPiece);
    } catch {
      // Ignore malformed frames rather than aborting the whole stream.
    }
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      // Frames are separated by a blank line. Handle both \n\n and \r\n\r\n.
      while ((sep = nextFrameBoundary(buffer)) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(boundaryEnd(buffer, sep));
        if (frame.trim()) handleFrame(frame);
      }
    }
    // Flush any trailing frame without a terminating blank line.
    buffer += decoder.decode();
    if (buffer.trim()) handleFrame(buffer);
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    handlers.onError?.(`Stream error: ${(err as Error).message}`);
  }
}

/** Index of the start of the frame separator (blank line), or -1. */
function nextFrameBoundary(buf: string): number {
  const a = buf.indexOf("\n\n");
  const b = buf.indexOf("\r\n\r\n");
  if (a === -1) return b;
  if (b === -1) return a;
  return Math.min(a, b);
}

/** Index just past the separator that starts at `sep`. */
function boundaryEnd(buf: string, sep: number): number {
  return buf.startsWith("\r\n\r\n", sep) ? sep + 4 : sep + 2;
}

// ---------------------------------------------------------------------------
// Admin API (all /admin/* data routes require the session cookie)
// ---------------------------------------------------------------------------

/** GET /admin/me — resolves true if authed, false on 401. Never throws on 401. */
export async function adminMe(): Promise<boolean> {
  try {
    await requestJson<{ ok: boolean }>("/admin/me");
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return false;
    throw err;
  }
}

/** POST /admin/login — sets the session cookie. Returns true on success, false on 401. */
export async function adminLogin(password: string): Promise<boolean> {
  try {
    await requestJson<{ ok: boolean }>("/admin/login", {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ password }),
    });
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return false;
    throw err;
  }
}

/** POST /admin/logout — clears the session cookie. */
export function adminLogout(): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>("/admin/logout", { method: "POST" });
}

/** GET /admin/conversations — inbox summaries, most-recent first. */
export async function adminListConversations(): Promise<ConversationSummary[]> {
  const data = await requestJson<{ conversations: ConversationSummary[] }>(
    "/admin/conversations"
  );
  return data.conversations;
}

/**
 * GET /admin/conversations/{id} — opens a thread: marks read + clears attention
 * server-side in one round-trip, and returns the full conversation.
 */
export function adminOpenConversation(
  conversationId: string
): Promise<Conversation> {
  return requestJson<Conversation>(
    `/admin/conversations/${encodeURIComponent(conversationId)}`
  );
}

/**
 * POST /admin/conversations/{id}/message — insert a `human` row. The Avatar does
 * NOT react to it. Returns the inserted row.
 */
export async function adminPostMessage(
  conversationId: string,
  content: string
): Promise<Message> {
  const data = await requestJson<{ message: Message }>(
    `/admin/conversations/${encodeURIComponent(conversationId)}/message`,
    {
      method: "POST",
      headers: JSON_HEADERS,
      body: JSON.stringify({ content }),
    }
  );
  return data.message;
}

/** POST /admin/conversations/{id}/resolve — clear needs_attention without replying. */
export function adminResolve(conversationId: string): Promise<{ ok: boolean }> {
  return requestJson<{ ok: boolean }>(
    `/admin/conversations/${encodeURIComponent(conversationId)}/resolve`,
    { method: "POST" }
  );
}
