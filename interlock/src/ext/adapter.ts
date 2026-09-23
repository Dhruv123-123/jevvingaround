import { effectiveBank } from "../core/bank.js";
import { compileEmailState } from "../core/compile.js";
import type { EmailState, QuestionDef, SenderHistory, Settings, Surface } from "../core/types.js";
import { SLACK_BANK } from "../surfaces/slack/bank.js";
import { compileSlackState, type SlackState } from "../surfaces/slack/compile.js";
import { extractDraft, findBody, findComposeRoots, findSendButton, type ComposeCounters } from "./gmail.js";
import { extractSlackDraft, findSlackBody, findSlackRoots, findSlackSend } from "./slack.js";

/** Everything the generic compose interlock needs to know about a host page. */
export interface SurfaceAdapter<S> {
  surface: Surface;
  findRoots(doc: Document): HTMLElement[];
  findSendButton(root: HTMLElement): HTMLElement | null;
  findBody(root: HTMLElement): HTMLElement | null;
  /** Keystroke that sends on this surface (Gmail: Ctrl/⌘+Enter; Slack: Enter). */
  isSendKey(e: KeyboardEvent): boolean;
  compile(root: HTMLElement, doc: Document, counters: ComposeCounters, history: SenderHistory, settings: Settings): S | null;
  bank(state: S, settings: Settings): QuestionDef[];
  l0(state: S): string[];
  /** addresses to remember as "sent to" after a successful send (email only) */
  recipients(state: S): string[];
}

export const gmailAdapter: SurfaceAdapter<EmailState> = {
  surface: "email",
  findRoots: findComposeRoots,
  findSendButton,
  findBody,
  isSendKey: (e) => e.key === "Enter" && (e.ctrlKey || e.metaKey),
  compile: (root, doc, counters, history, settings) => {
    const raw = extractDraft(root, doc, counters);
    if (!raw.recipients.length && !raw.bodyText.trim()) return null;
    return compileEmailState(raw, history, { redaction: settings.redaction });
  },
  bank: (state, settings) => effectiveBank(settings, state),
  l0: (s) => s.l0_flags,
  recipients: (s) => s.recipients.map((r) => r.addr).filter((a) => !a.startsWith("<")),
};

export const slackAdapter: SurfaceAdapter<SlackState> = {
  surface: "slack",
  findRoots: findSlackRoots,
  findSendButton: findSlackSend,
  findBody: findSlackBody,
  isSendKey: (e) => e.key === "Enter" && !e.shiftKey && !e.altKey && !e.isComposing,
  compile: (root, doc, counters, _history, settings) => {
    const raw = extractSlackDraft(root, doc, counters);
    if (!raw.text.trim()) return null;
    return compileSlackState(raw, { redaction: settings.redaction });
  },
  bank: (_state, settings) => {
    const disabled = new Set(settings.disabledQuestions);
    return [...SLACK_BANK, ...settings.extraQuestions.filter((q) => q.origin !== "builtin")]
      .filter((q) => !disabled.has(q.id))
      .map((q) => (settings.thresholdOverrides[q.id] ? { ...q, thresholds: { ...q.thresholds, ...settings.thresholdOverrides[q.id] } } : q));
  },
  l0: (s) => s.l0_flags,
  recipients: () => [],
};

export function adapterFor(hostname: string): SurfaceAdapter<any> | null {
  if (hostname === "mail.google.com") return gmailAdapter;
  if (hostname === "app.slack.com") return slackAdapter;
  // local fixtures pick their adapter with a meta tag so the e2e can run both on 127.0.0.1
  const meta = document.querySelector<HTMLMetaElement>('meta[name="interlock-surface"]')?.content;
  if (meta === "slack") return slackAdapter;
  if (meta === "email") return gmailAdapter;
  return null;
}
