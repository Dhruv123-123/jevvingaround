import type { CompiledRecipient, EmailState, RawDraft, SenderHistory, Settings } from "./types.js";

const HEAD_CHARS = 600;
const TAIL_CHARS = 300;
const KEY_SENTENCE_RE = /\b(don'?t|do not|confidential|internal only|not (?:to be )?shared|by (?:mon|tues|wednes|thurs|fri|satur|sun)day|deadline|asap|urgent|attached|attachment|password|token|api key|secret|wire|invoice|price|pricing|discount)\b/i;
const PLACEHOLDER_RE = /\b(TODO|TBD|XXX|FIXME|\[insert[^\]]*\]|\[name\]|lorem ipsum)\b|\{\{[^}]*\}\}/i;
const ATTACH_MENTION_RE = /\b(attached|attachment|enclosed|see the (?:file|doc|deck|sheet)|find (?:the )?(?:file|doc|deck|sheet))\b/i;
const SECRET_RE = /\b(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)\b|password\s*[:=]\s*\S{6,}/i;
const EMAIL_RE = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;
const PHONE_RE = /(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b/g;
const CARD_RE = /\b(?:\d[ -]?){13,19}\b/g;

export function domainOf(addr: string): string {
  const at = addr.lastIndexOf("@");
  return at < 0 ? "" : addr.slice(at + 1).toLowerCase();
}

/** Two addresses that differ by <=2 edits (before the @) are autocomplete-slip candidates. */
function editDistanceLE2(a: string, b: string): boolean {
  if (Math.abs(a.length - b.length) > 2) return false;
  const dp: number[] = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    let prev = dp[0]!;
    dp[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const tmp = dp[j]!;
      dp[j] = Math.min(dp[j]! + 1, dp[j - 1]! + 1, prev + (a[i - 1] === b[j - 1] ? 0 : 1));
      prev = tmp;
    }
  }
  return dp[b.length]! <= 2;
}

export function sentencesMatching(text: string, re: RegExp, max = 4): string[] {
  const out: string[] = [];
  for (const s of text.split(/(?<=[.!?])\s+|\n+/)) {
    const t = s.trim();
    if (t && re.test(t)) {
      out.push(t.length > 200 ? t.slice(0, 200) + "…" : t);
      if (out.length >= max) break;
    }
  }
  return out;
}

export interface CompileOptions {
  now?: number;
  redaction?: Settings["redaction"];
}

/**
 * Turn a raw draft into the compact, pre-digested state Jev sees.
 * Everything quantitative is computed here; Jev only gets facts and short text.
 */
export function compileEmailState(raw: RawDraft, history: SenderHistory, opts: CompileOptions = {}): EmailState {
  const now = opts.now ?? Date.now();
  const orgDomain = domainOf(raw.senderAddr);
  const threadParticipants = new Set<string>();
  for (const m of raw.thread) {
    threadParticipants.add(m.from.toLowerCase());
    for (const a of m.toAddrs) threadParticipants.add(a.toLowerCase());
  }
  threadParticipants.delete(raw.senderAddr.toLowerCase());

  const known = Object.keys(history.sentTo);
  const seenDomains = new Set(known.map(domainOf));
  const recipientAddrs = new Set(raw.recipients.map((r) => r.addr.toLowerCase()));

  const recipients: CompiledRecipient[] = raw.recipients.map((r) => {
    const addr = r.addr.toLowerCase();
    const local = addr.split("@")[0] ?? "";
    let lookalike: string | undefined;
    if (!(addr in history.sentTo)) {
      for (const k of known) {
        if (k !== addr && editDistanceLE2(local, k.split("@")[0] ?? "")) { lookalike = k; break; }
      }
    }
    const c: CompiledRecipient = {
      addr,
      kind: r.kind,
      external: domainOf(addr) !== orgDomain,
      first_time_ever: !(addr in history.sentTo),
      domain_first_time: !seenDomains.has(domainOf(addr)),
      in_original_thread: threadParticipants.has(addr),
    };
    if (lookalike) c.looks_like_a_known_contact = lookalike;
    return c;
  });

  const body = raw.bodyText.replace(/\r/g, "").trim();
  const last = raw.thread.length ? raw.thread[raw.thread.length - 1]! : null;
  const fiveMinAgo = now - 5 * 60_000;

  const l0: string[] = [];
  if (SECRET_RE.test(body)) l0.push("secret_pattern_in_body");
  if (raw.attachments.some((a) => /final|confidential|internal|salary|payroll|pricing/i.test(a))) l0.push("sensitive_attachment_name");
  if (recipients.some((r) => r.external)) l0.push("external_recipient_present");
  if (recipients.some((r) => r.looks_like_a_known_contact)) l0.push("lookalike_recipient");
  if (ATTACH_MENTION_RE.test(body) && raw.attachments.length === 0) l0.push("mentions_attachment_none_attached");
  if (raw.isReplyAll && raw.recipients.length >= 5) l0.push("large_reply_all");

  const state: EmailState = {
    action: "email.send",
    draft: {
      subject: raw.subject.trim(),
      body_head: body.slice(0, HEAD_CHARS),
      body_tail: body.length > HEAD_CHARS + TAIL_CHARS ? body.slice(-TAIL_CHARS) : "",
      body_chars: body.length,
      attachments: raw.attachments,
      mentions_attachment_in_text: ATTACH_MENTION_RE.test(body),
      has_placeholders: PLACEHOLDER_RE.test(body) || PLACEHOLDER_RE.test(raw.subject),
      key_sentences: sentencesMatching(body, KEY_SENTENCE_RE),
    },
    recipients,
    thread: raw.thread.length
      ? {
          message_count: raw.thread.length,
          participants_not_in_recipients: [...threadParticipants].filter((p) => !recipientAddrs.has(p)),
          last_msg_from: last!.from.toLowerCase(),
          last_msg_head: last!.text.trim().slice(0, 400),
          is_reply_all: raw.isReplyAll,
          original_recipient_count: last!.toAddrs.length + 1,
        }
      : null,
    sender_context: {
      sends_in_last_5_min: history.recentSends.filter((t) => t >= fiveMinAgo).length,
      local_time: formatLocalTime(now),
      draft_age: draftAge(now - raw.draftOpenedAt),
      deletions_ratio: raw.keystrokes ? Math.round((raw.deletions / raw.keystrokes) * 100) / 100 : 0,
      external_recipient_count: recipients.filter((r) => r.external).length,
      recipient_count: recipients.length,
    },
    l0_flags: l0,
  };

  return redact(state, opts.redaction ?? "body");
}

/** Hour granularity: fine for "late Friday" judgments, stable across the seconds before a click. */
function formatLocalTime(ms: number): string {
  const d = new Date(ms);
  const day = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()];
  return `${day} ${String(d.getHours()).padStart(2, "0")}h`;
}

function draftAge(ms: number): EmailState["sender_context"]["draft_age"] {
  if (ms < 30_000) return "<30s";
  if (ms < 120_000) return "30s-2m";
  if (ms < 600_000) return "2-10m";
  return ">10m";
}

/**
 * Redaction runs AFTER features are computed, so nothing is lost for the model that matters.
 * "body": scrub emails/phones/card-ish numbers inside free text; recipient addrs stay.
 * "strict": also replace recipient addrs with typed placeholders that keep only the domain.
 */
export function redact(state: EmailState, mode: Settings["redaction"]): EmailState {
  if (mode === "none") return state;
  const scrub = (s: string) => s.replace(EMAIL_RE, "<EMAIL>").replace(CARD_RE, "<CARD_NUMBER>").replace(PHONE_RE, "<PHONE>");
  const out: EmailState = structuredClone(state);
  out.draft.body_head = scrub(out.draft.body_head);
  out.draft.body_tail = scrub(out.draft.body_tail);
  out.draft.key_sentences = out.draft.key_sentences.map(scrub);
  if (out.thread) out.thread.last_msg_head = out.thread.last_msg_head && scrub(out.thread.last_msg_head);
  if (mode === "strict") {
    const map = new Map<string, string>();
    const tag = (addr: string) => {
      if (!map.has(addr)) map.set(addr, `<R${map.size + 1}@${domainOf(addr)}>`);
      return map.get(addr)!;
    };
    for (const r of out.recipients) {
      const t = tag(r.addr);
      r.addr = t;
      if (r.looks_like_a_known_contact) r.looks_like_a_known_contact = tag(r.looks_like_a_known_contact);
    }
    if (out.thread) {
      out.thread.participants_not_in_recipients = out.thread.participants_not_in_recipients.map(tag);
      out.thread.last_msg_from = out.thread.last_msg_from && tag(out.thread.last_msg_from);
    }
  }
  return out;
}
