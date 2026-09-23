import type { RawSlackDraft } from "../surfaces/slack/compile.js";
import type { ComposeCounters } from "./gmail.js";

/** Slack web (app.slack.com) selectors, first form mirrored by test/fixtures/slack.html. */
export const SLACK_SELECTORS = {
  body: ['div[data-qa="message_input"] .ql-editor[contenteditable="true"]', 'div[data-qa="message_input"][contenteditable="true"]', '.ql-editor[contenteditable="true"]'],
  send: ['button[data-qa="texty_send_button"]', 'button[aria-label="Send now"]', 'button[aria-label^="Send"]'],
  channelName: ['[data-qa="channel_name"]', '[data-qa="channel_header_title"]', 'h1'],
  memberCount: ['[data-qa="channel_members_count"]', '[data-qa*="members"]', '[data-member-count]'],
  threadPane: ['[data-qa="threads_flexpane"]', '[data-qa="thread_view"]'],
  message: ['[data-qa="virtual-list-item"]', '[data-qa="message_container"]', '[data-message]'],
  messageAuthor: ['[data-qa="message_sender_name"]', '[data-qa="message_sender"]', '.c-message__sender'],
  messageText: ['[data-qa="message-text"]', '.c-message__body', '[data-message-text]'],
  attachment: ['[data-qa="composer_file_preview"]', '[data-qa="file_preview"]', '[data-composer-attachment]'],
  senderName: ['[data-qa="user-button"]', '[data-qa="current_user_name"]', '[data-current-user]'],
  externalBadge: ['[data-qa="slack_connect_badge"]', '[data-qa*="shared"]', '[data-external-shared]'],
  privateIcon: ['[data-qa="channel_lock_icon"]', '[data-private="true"]'],
};

function q<T extends Element = HTMLElement>(root: ParentNode, sels: string[]): T | null {
  for (const s of sels) { const el = root.querySelector<T>(s); if (el) return el; }
  return null;
}
function qa<T extends Element = HTMLElement>(root: ParentNode, sels: string[]): T[] {
  for (const s of sels) { const els = root.querySelectorAll<T>(s); if (els.length) return [...els]; }
  return [];
}

/** The composer root: the nearest ancestor of the editor that also holds the send button. */
export function findSlackRoots(doc: Document): HTMLElement[] {
  const roots = new Set<HTMLElement>();
  for (const body of qa(doc, SLACK_SELECTORS.body)) {
    let el: HTMLElement | null = body.parentElement;
    while (el && el !== doc.body) { if (q(el, SLACK_SELECTORS.send)) { roots.add(el); break; } el = el.parentElement; }
  }
  return [...roots];
}
export const findSlackSend = (root: HTMLElement) => q(root, SLACK_SELECTORS.send);
export const findSlackBody = (root: HTMLElement) => q(root, SLACK_SELECTORS.body);

export function extractSlackDraft(root: HTMLElement, doc: Document, counters: ComposeCounters): RawSlackDraft {
  const inThread = !!root.closest(SLACK_SELECTORS.threadPane.join(","));
  const nameEl = q(doc, SLACK_SELECTORS.channelName);
  const name = nameEl?.textContent?.trim() ?? "";
  const mcText = q(doc, SLACK_SELECTORS.memberCount)?.textContent ?? q(doc, SLACK_SELECTORS.memberCount)?.getAttribute("data-member-count") ?? "";
  const mc = mcText.match(/\d[\d,]*/);
  const kind: RawSlackDraft["channel"]["kind"] = inThread ? "thread" : name.startsWith("#") ? "channel" : nameEl?.getAttribute("data-channel-kind") as RawSlackDraft["channel"]["kind"] | null ?? (name ? "dm" : "unknown");
  const scope = inThread ? (root.closest(SLACK_SELECTORS.threadPane.join(",")) as HTMLElement) : doc;
  const recent = qa(scope, SLACK_SELECTORS.message).slice(-6).map((m) => ({
    author: q(m, SLACK_SELECTORS.messageAuthor)?.textContent?.trim() ?? "?",
    text: q(m, SLACK_SELECTORS.messageText)?.textContent ?? "",
  })).filter((m) => m.text.trim());
  return {
    text: findSlackBody(root)?.innerText ?? "",
    channel: {
      name,
      kind,
      memberCount: mc ? Number(mc[0].replace(/,/g, "")) : null,
      isPrivate: q(doc, SLACK_SELECTORS.privateIcon) ? true : null,
      isSharedExternal: q(doc, SLACK_SELECTORS.externalBadge) ? true : null,
    },
    recent,
    hasAttachment: !!q(root, SLACK_SELECTORS.attachment),
    senderName: q(doc, SLACK_SELECTORS.senderName)?.getAttribute("aria-label")?.replace(/^User: /, "") ?? q(doc, SLACK_SELECTORS.senderName)?.textContent?.trim() ?? null,
    draftOpenedAt: counters.openedAt,
    keystrokes: counters.keystrokes,
    deletions: counters.deletions,
  };
}
