import { compileEmailState } from "../core/compile.js";
import type { EmailState, QuestionDef, SenderHistory, Settings, Surface } from "../core/types.js";
import { PACKS } from "../generated/packs.js";
import type { GatePack } from "../node/gate.js";
import { applySettings } from "../pack/settings.js";
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
  /** the pack for this state: built-in pack + user settings + any per-state dynamic questions */
  pack(state: S, settings: Settings): GatePack;
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
  pack: (state, settings) => applySettings(PACKS["email"]!, settings, recipientChoice(state)),
  l0: (s) => s.l0_flags,
  recipients: (s) => s.recipients.map((r) => r.addr).filter((a) => !a.startsWith("<")),
};

/** `wrong_recipient__which`: a choice over the actual recipients, so the reason can name the suspect one. */
function recipientChoice(state: EmailState): QuestionDef[] {
  if (state.recipients.length < 2) return [];
  const criteria: Record<string, string | null> = { none: "All recipients look right" };
  for (const r of state.recipients.slice(0, 40)) criteria[r.addr] = null;
  return [{ id: "wrong_recipient__which", type: "choice", instructions: "If any recipient looks like a mistake, which one?", criteria, weight: 0 }];
}

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
  pack: (_state, settings) => applySettings(PACKS["slack"]!, settings),
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
