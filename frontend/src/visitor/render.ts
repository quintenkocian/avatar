// DOM rendering for visitor-chat message bubbles. Every node here matches the
// markup in design-system/mockups/Visitor Chat.html and the component classes in
// components.css. Roles render exactly per design-system §4:
//   - visitor: .msg--visitor, right aligned, .avatar-initials (blue token)
//   - avatar:  .msg--avatar, left, avatar-robot-round.png in .avatar-twin (cyan),
//              name "Avatar", optional .tool-status lines above the bubble
//   - human:   .msg--human, left, avatar-human.png in .avatar-human (yellow ring +
//              tint + glow), labelled "{owner} · live" (owner from /api/config)
//
// No emoji, no gradients in chrome — the design system supplies all colour.

import type { Message, ToolCallSummary } from "../api";
import { formatTime } from "../util";
import { renderMarkdown } from "../markdown";

const ROBOT_AVATAR = "/avatar-robot-round.png";
const HUMAN_AVATAR = "/avatar-human.png";

/** Build an SVG icon node that references the shared sprite (#i-<name>). */
function icon(name: string, cls = "icon"): SVGSVGElement {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("class", cls);
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  // Both attribute forms are honoured; href is the modern one, xlink:href the
  // legacy fallback some engines still prefer for external sprites.
  use.setAttribute("href", `/icons.svg#i-${name}`);
  use.setAttributeNS(
    "http://www.w3.org/1999/xlink",
    "xlink:href",
    `/icons.svg#i-${name}`
  );
  svg.appendChild(use);
  return svg;
}

/** A short, human-friendly label for a known tool, with optional detail. */
function toolLabel(name: string, detail?: string | null): { text: string; iconName: string } {
  const d = (detail ?? "").trim();
  switch (name) {
    case "faq_tool":
      return { text: d ? `Looked up ${d}` : "Looked up the FAQ", iconName: "check" };
    case "push_tool":
      return { text: `Sent a heads-up`, iconName: "mail" };
    case "fetch":
      return { text: d ? `Read ${d}` : "Read the linked job posting", iconName: "globe" };
    default:
      return { text: d ? `${name} · ${d}` : name, iconName: "tool" };
  }
}

/** A live tool-status row (the "calling…" or "done" state) for a given tool. */
export function buildToolStatusRow(
  name: string,
  detail: string | null,
  done: boolean
): HTMLDivElement {
  const row = document.createElement("div");
  row.className = done ? "tool-status is-done" : "tool-status";
  row.dataset.tool = name;
  if (done) {
    const { text, iconName } = toolLabel(name, detail);
    row.appendChild(icon(iconName));
    const span = document.createElement("span");
    span.textContent = `${text} · ${name}`;
    row.appendChild(span);
  } else {
    row.appendChild(icon("tool"));
    const span = document.createElement("span");
    // The trailing animated ellipsis is provided by `.tool-status .dots::after`.
    span.innerHTML = `Calling <span>${escapeText(name)}</span><span class="dots"></span>`;
    row.appendChild(span);
  }
  return row;
}

/** Escape free text for safe inline insertion (used only for tool names). */
function escapeText(value: string): string {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

interface VisitorOpts {
  initialsText: string;
  content: string;
  createdAt?: string;
}

/** Render a visitor message bubble (right-aligned initials token). */
export function buildVisitorMessage(opts: VisitorOpts): HTMLDivElement {
  const msg = document.createElement("div");
  msg.className = "msg msg--visitor";

  const token = document.createElement("span");
  token.className = "avatar-initials";
  const label = opts.initialsText || "?";
  // A word label (e.g. the "Anon" placeholder) gets a smaller, mixed-case fit so
  // it sits comfortably in the same token used for 2-letter initials.
  if (label.length > 2) token.classList.add("avatar-initials--label");
  token.textContent = label;
  msg.appendChild(token);

  const body = document.createElement("div");
  body.className = "msg-body";

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  const time = document.createElement("span");
  time.className = "msg-time";
  time.textContent = formatTime(opts.createdAt ?? new Date());
  meta.appendChild(time);
  body.appendChild(meta);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = renderMarkdown(opts.content);
  body.appendChild(bubble);

  msg.appendChild(body);
  return msg;
}

export interface AvatarMessageNodes {
  msg: HTMLDivElement;
  toolStatuses: HTMLDivElement;
  bubble: HTMLDivElement;
  meta: HTMLDivElement;
}

interface AvatarOpts {
  createdAt?: string;
  /** Adds the "instant · Q{n}" tag for Qn shortcut replies. */
  instantQuestion?: number | null;
}

/**
 * Render an avatar message shell and return handles for streaming. The bubble
 * starts empty; the caller appends tokens (re-rendering markdown) and tool rows.
 */
export function buildAvatarMessage(opts: AvatarOpts = {}): AvatarMessageNodes {
  const msg = document.createElement("div");
  msg.className = "msg msg--avatar";

  const avatar = document.createElement("div");
  avatar.className = "avatar avatar-twin";
  avatar.style.backgroundImage = `url('${ROBOT_AVATAR}')`;
  msg.appendChild(avatar);

  const body = document.createElement("div");
  body.className = "msg-body";

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  const name = document.createElement("span");
  name.className = "msg-name";
  name.textContent = "Avatar";
  meta.appendChild(name);

  if (opts.instantQuestion != null) {
    const tag = document.createElement("span");
    tag.className = "instant-tag";
    tag.textContent = `instant · Q${opts.instantQuestion}`;
    meta.appendChild(tag);
  }

  const time = document.createElement("span");
  time.className = "msg-time";
  time.textContent = formatTime(opts.createdAt ?? new Date());
  meta.appendChild(time);
  body.appendChild(meta);

  // Container for tool-status rows (above the bubble). Empty until tools fire.
  const toolStatuses = document.createElement("div");
  toolStatuses.className = "tool-statuses";
  body.appendChild(toolStatuses);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  body.appendChild(bubble);

  msg.appendChild(body);
  return { msg, toolStatuses, bubble, meta };
}

interface HumanOpts {
  ownerName: string;
  content: string;
  createdAt?: string;
}

/** Render the human ("live" owner) bubble — photo + yellow ring + tint + glow. */
export function buildHumanMessage(opts: HumanOpts): HTMLDivElement {
  const msg = document.createElement("div");
  msg.className = "msg msg--human";

  const avatar = document.createElement("div");
  avatar.className = "avatar avatar-human";
  avatar.style.backgroundImage = `url('${HUMAN_AVATAR}')`;
  const spark = document.createElement("span");
  spark.className = "spark-badge";
  spark.appendChild(icon("spark"));
  avatar.appendChild(spark);
  msg.appendChild(avatar);

  const body = document.createElement("div");
  body.className = "msg-body";

  const meta = document.createElement("div");
  meta.className = "msg-meta";
  const tag = document.createElement("span");
  tag.className = "human-tag";
  tag.appendChild(icon("live"));
  // Resolved-conflict #1: show "{owner_name} · live", owner from /api/config.
  const tagText = document.createTextNode(` ${opts.ownerName} · live`);
  tag.appendChild(tagText);
  meta.appendChild(tag);

  const time = document.createElement("span");
  time.className = "msg-time";
  time.textContent = formatTime(opts.createdAt ?? new Date());
  meta.appendChild(time);
  body.appendChild(meta);

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = renderMarkdown(opts.content);
  body.appendChild(bubble);

  msg.appendChild(body);
  return msg;
}

/**
 * Render a fully-persisted Message row (used to restore a thread from cookie and
 * to render polled rows). Returns null for unknown roles.
 */
export function buildMessageFromRow(
  row: Message,
  ownerName: string,
  visitorInitials: string
): HTMLElement | null {
  if (row.role === "visitor") {
    return buildVisitorMessage({
      initialsText: visitorInitials,
      content: row.content,
      createdAt: row.created_at,
    });
  }
  if (row.role === "human") {
    return buildHumanMessage({
      ownerName,
      content: row.content,
      createdAt: row.created_at,
    });
  }
  if (row.role === "avatar") {
    const instant =
      row.tool_calls && typeof row.tool_calls.instant === "number"
        ? row.tool_calls.instant
        : null;
    const nodes = buildAvatarMessage({
      createdAt: row.created_at,
      instantQuestion: instant,
    });
    // Replay any persisted tool calls as completed rows above the bubble.
    const tools: ToolCallSummary[] | undefined = row.tool_calls?.tools;
    if (Array.isArray(tools)) {
      for (const t of tools) {
        nodes.toolStatuses.appendChild(
          buildToolStatusRow(t.name, t.detail ?? null, true)
        );
      }
    }
    nodes.bubble.innerHTML = renderMarkdown(row.content);
    return nodes.msg;
  }
  return null;
}

export { ROBOT_AVATAR, HUMAN_AVATAR };
