import type { RawDraft, RawRecipient, RawThreadMessage } from "../core/types.js";

/**
 * Every Gmail selector lives here. Gmail's DOM is obfuscated and shifts; each entry has fallbacks
 * and the fixture page in test/fixtures mirrors the *first* form of each so the e2e stays honest.
 */
export const SELECTORS = {
  body: ['div[aria-label="Message Body"][contenteditable="true"]', 'div[g_editable="true"][role="textbox"]', 'div[role="textbox"][contenteditable="true"]'],
  send: ['div[role="button"][aria-label^="Send"]', 'div[role="button"][data-tooltip^="Send"]', 'button[aria-label^="Send"]'],
  subject: ['input[name="subjectbox"]', 'input[aria-label="Subject"]'],
  recipientArea: (kind: string) => [`div[name="${kind}"]`, `td[name="${kind}"]`, `[aria-label="${kind.toUpperCase()}"]`, `[data-recipient-kind="${kind}"]`],
  chip: ['[role="option"][data-hovercard-id]', 'span[email]', '[data-hovercard-id]'],
  typedRecipient: ['input[aria-label$="recipients"]', 'input[role="combobox"]', 'textarea[name]'],
  attachmentInput: ['input[name="attach"]'],
  attachmentName: ['.vI', '[data-attachment-name]'],
  threadMessage: ['div[role="listitem"].adn', 'div[role="listitem"][data-message-id]', 'div[role="listitem"]'],
  threadBody: ['.a3s', '[data-message-body]'],
  threadSubject: ['h2[data-thread-perm-id]', '.hP', '[data-thread-subject]'],
  accountLink: ['a[aria-label*="Google Account"]', '[data-account-email]'],
  fromField: ['span[email][name]', '.az2 span[email]', '[data-from-email]'],
};

function q<T extends Element = HTMLElement>(root: ParentNode, sels: string[]): T | null {
  for (const s of sels) { const el = root.querySelector<T>(s); if (el) return el; }
  return null;
}
function qa<T extends Element = HTMLElement>(root: ParentNode, sels: string[]): T[] {
  for (const s of sels) { const els = root.querySelectorAll<T>(s); if (els.length) return [...els]; }
  return [];
}

/** A compose root is the smallest ancestor of a Message Body editor that also contains a Send button. */
export function findComposeRoots(doc: Document = document): HTMLElement[] {
  const roots = new Set<HTMLElement>();
  for (const body of qa(doc, SELECTORS.body)) {
    let el: HTMLElement | null = body.parentElement;
    while (el && el !== doc.body) {
      if (q(el, SELECTORS.send)) { roots.add(el); break; }
      el = el.parentElement;
    }
  }
  return [...roots];
}

export function findSendButton(root: HTMLElement): HTMLElement | null { return q(root, SELECTORS.send); }
export function findBody(root: HTMLElement): HTMLElement | null { return q(root, SELECTORS.body); }

const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i;

function chipEmail(el: Element): string | null {
  const e = el.getAttribute("data-hovercard-id") ?? el.getAttribute("email") ?? el.getAttribute("data-email");
  if (e && EMAIL_RE.test(e)) return e.toLowerCase();
  const m = (el.textContent ?? "").match(EMAIL_RE);
  return m ? m[0].toLowerCase() : null;
}

export function extractRecipients(root: HTMLElement): RawRecipient[] {
  const out: RawRecipient[] = [];
  const seen = new Set<string>();
  for (const kind of ["to", "cc", "bcc"] as const) {
    const area = q(root, SELECTORS.recipientArea(kind));
    if (!area) continue;
    for (const chip of qa(area, SELECTORS.chip)) {
      const addr = chipEmail(chip);
      if (addr && !seen.has(addr)) { seen.add(addr); out.push({ addr, kind, name: chip.getAttribute("data-name") ?? chip.getAttribute("name") ?? undefined }); }
    }
    // text typed but not yet turned into a chip still counts: it is what will be sent
    const typed = q<HTMLInputElement>(area, SELECTORS.typedRecipient);
    if (typed?.value) for (const m of typed.value.match(new RegExp(EMAIL_RE.source, "gi")) ?? []) {
      const addr = m.toLowerCase();
      if (!seen.has(addr)) { seen.add(addr); out.push({ addr, kind }); }
    }
  }
  return out;
}

export function extractAttachments(root: HTMLElement): string[] {
  const names = new Set<string>();
  for (const i of qa<HTMLInputElement>(root, SELECTORS.attachmentInput)) {
    const v = i.value || "";
    const name = v.includes(":") ? v.slice(0, v.indexOf(":")) : v;
    if (name) names.add(name);
  }
  if (!names.size) for (const el of qa(root, SELECTORS.attachmentName)) { const t = el.textContent?.trim(); if (t) names.add(t); }
  return [...names];
}

export function extractThread(doc: Document, max = 5): RawThreadMessage[] {
  const items = qa(doc, SELECTORS.threadMessage);
  const msgs: RawThreadMessage[] = [];
  for (const item of items.slice(-max)) {
    const body = q(item, SELECTORS.threadBody);
    const emails = [...item.querySelectorAll("[email], [data-hovercard-id]")]
      .map((e) => (e.getAttribute("email") ?? e.getAttribute("data-hovercard-id") ?? "").toLowerCase())
      .filter((e) => EMAIL_RE.test(e));
    if (!emails.length) continue;
    const from = emails[0]!;
    const toAddrs = [...new Set(emails.slice(1))].filter((e) => e !== from);
    msgs.push({ from, toAddrs, text: (body?.textContent ?? "").trim().slice(0, 1000) });
  }
  return msgs;
}

export function extractSubject(root: HTMLElement, doc: Document): string {
  const box = q<HTMLInputElement>(root, SELECTORS.subject);
  if (box) return box.value;
  return q(doc, SELECTORS.threadSubject)?.textContent?.trim() ?? "";
}

export function extractSenderAddr(root: HTMLElement, doc: Document): string {
  const from = q(root, SELECTORS.fromField);
  const fe = from?.getAttribute("email") ?? from?.getAttribute("data-from-email");
  if (fe && EMAIL_RE.test(fe)) return fe.toLowerCase();
  const acct = q(doc, SELECTORS.accountLink);
  const label = acct?.getAttribute("aria-label") ?? acct?.getAttribute("data-account-email") ?? "";
  const m = label.match(EMAIL_RE);
  return m ? m[0].toLowerCase() : "unknown@unknown.invalid";
}

export interface ComposeCounters { openedAt: number; keystrokes: number; deletions: number }

export function extractDraft(root: HTMLElement, doc: Document, counters: ComposeCounters): RawDraft {
  const recipients = extractRecipients(root);
  const thread = extractThread(doc);
  return {
    subject: extractSubject(root, doc),
    bodyText: findBody(root)?.innerText ?? "",
    recipients,
    attachments: extractAttachments(root),
    thread,
    isReplyAll: thread.length > 0 && recipients.length >= 2,
    senderAddr: extractSenderAddr(root, doc),
    draftOpenedAt: counters.openedAt,
    keystrokes: counters.keystrokes,
    deletions: counters.deletions,
  };
}
